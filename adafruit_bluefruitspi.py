# The MIT License (MIT)
#
# Copyright (c) 2018 Kevin Townsend for Adafruit_Industries
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
"""
`adafruit_bluefruitspi`
====================================================

Helper class to work with the Adafruit Bluefruit LE SPI friend breakout.

* Author(s): Kevin Townsend

Implementation Notes
--------------------

**Hardware:**

"* `Adafruit Bluefruit LE SPI Friend <https://www.adafruit.com/product/2633>`_"

**Software and Dependencies:**

* Adafruit CircuitPython firmware for the supported boards:
  https://github.com/adafruit/circuitpython/releases

* Adafruit's Bus Device library: https://github.com/adafruit/Adafruit_CircuitPython_BusDevice
"""

# imports

__version__ = "0.0.0-auto.0"
__repo__ = "https://github.com/adafruit/Adafruit_CircuitPython_BluefruitSPI.git"

import time
from digitalio import Direction, Pull
from adafruit_bus_device.spi_device import SPIDevice
from micropython import const
import struct


class MsgType:  #pylint: disable=too-few-public-methods,bad-whitespace
    """An enum-like class representing the possible message types.
    Possible values are:
    - ``MsgType.COMMAND``
    - ``MsgType.RESPONSE``
    - ``MsgType.ALERT``
    - ``MsgType.ERROR``
    """
    COMMAND   = const(0x10)  # Command message
    RESPONSE  = const(0x20)  # Response message
    ALERT     = const(0x40)  # Alert message
    ERROR     = const(0x80)  # Error message


class SDEPCommand:  #pylint: disable=too-few-public-methods,bad-whitespace
    """An enum-like class representing the possible SDEP commands.
    Possible values are:
    - ``SDEPCommand.INITIALIZE``
    - ``SDEPCommand.ATCOMMAND``
    - ``SDEPCommand.BLEUART_TX``
    - ``SDEPCommand.BLEUART_RX``
    """
    INITIALIZE = const(0xBEEF) # Resets the Bluefruit device
    ATCOMMAND  = const(0x0A00) # AT command wrapper
    BLEUART_TX = const(0x0A01) # BLE UART transmit data
    BLEUART_RX = const(0x0A02) # BLE UART read data


class ArgType:  #pylint: disable=too-few-public-methods,bad-whitespace
    """An enum-like class representing the possible argument types.
    Possible values are
    - ``ArgType.STRING``
    - ``ArgType.BYTEARRAY``
    - ``ArgType.INT32``
    - ``ArgType.UINT32``
    - ``ArgType.INT16``
    - ``ArgType.UINT16``
    - ``ArgType.INT8``
    - ``ArgType.UINT8``
    """
    STRING    = const(0x0100) # String data type
    BYTEARRAY = const(0x0200) # Byte array data type
    INT32     = const(0x0300) # Signed 32-bit integer data type
    UINT32    = const(0x0400) # Unsigned 32-bit integer data type
    INT16     = const(0x0500) # Signed 16-bit integer data type
    UINT16    = const(0x0600) # Unsigned 16-bit integer data type
    INT8      = const(0x0700) # Signed 8-bit integer data type
    UINT8     = const(0x0800) # Unsigned 8-bit integer data type


class ErrorCode:  #pylint: disable=too-few-public-methods,bad-whitespace
    """An enum-like class representing possible error codes.
    Possible values are
    - ``ErrorCode.``
    """
    INVALIDMSGTYPE = const(0x8021) # SDEP: Unexpected SDEP MsgType
    INVALIDCMDID   = const(0x8022) # SDEP: Unknown command ID
    INVALIDPAYLOAD = const(0x8023) # SDEP: Payload problem
    INVALIDLEN     = const(0x8024) # SDEP: Indicated len too large
    INVALIDINPUT   = const(0x8060) # AT: Invalid data
    UNKNOWNCMD     = const(0x8061) # AT: Unknown command name
    INVALIDPARAM   = const(0x8062) # AT: Invalid param value
    UNSUPPORTED    = const(0x8063) # AT: Unsupported command


class BluefruitSPI:
    """Helper for the Bluefruit LE SPI Friend"""

    def __init__(self, spi, cs, irq, reset, debug=False):
        self._irq = irq
        self._buf_tx = bytearray(20)
        self._buf_rx = bytearray(20)
        self._debug = debug

        # Reset
        reset.direction = Direction.OUTPUT
        reset.value = False
        time.sleep(0.01)
        reset.value = True
        time.sleep(0.5)

        # CS is an active low output
        cs.direction = Direction.OUTPUT
        cs.value = True

        # irq line is active high input, so set a pulldown as a precaution
        self._irq.direction = Direction.INPUT
        self._irq.pull = Pull.DOWN

        self._spi_device = SPIDevice(spi, cs,
                                     baudrate=4000000, phase=0, polarity=0)

    def _cmd(self, cmd):
        """
        Executes the supplied AT command, which must be terminated with
        a new-line character.
        Returns msgtype, rspid, rsp, which are 8-bit int, 16-bit int and a
        bytearray.
        :param cmd: The new-line terminated AT command to execute.
        """
        # Make sure we stay within the 255 byte limit
        if len(cmd) > 127:
            if self._debug:
                print("ERROR: Command too long.")
            raise ValueError('Command too long.')

        more = 0x80 # More bit is in pos 8, 1 = more data available
        pos = 0
        while len(cmd) - pos:
            # Construct the SDEP packet
            if len(cmd) - pos <= 16:
                # Last or sole packet
                more = 0
            plen = len(cmd) - pos
            if plen > 16:
                plen = 16
            # Note the 'more' value in bit 8 of the packet len
            struct.pack_into("<BHB16s", self._buf_tx, 0,
                             MsgType.COMMAND, SDEPCommand.ATCOMMAND,
                             plen | more, cmd[pos:pos+plen])
            if self._debug:
                print("Writing: ", [hex(b) for b in self._buf_tx])
            # Update the position if there is data remaining
            pos += plen

            # Send out the SPI bus
            with self._spi_device as spi:
                spi.write(self._buf_tx, end=len(cmd) + 4)

        # Wait up to 200ms for a response
        timeout = 0.2
        while timeout > 0 and not self._irq.value:
            time.sleep(0.01)
            timeout -= 0.01
        if timeout <= 0:
            if self._debug:
                print("ERROR: Timed out waiting for a response.")
            raise RuntimeError('Timed out waiting for a response.')

        # Retrieve the response message
        msgtype = 0
        rspid = 0
        rsplen = 0
        rsp = b""
        while self._irq.value is True:
            # Read the current response packet
            time.sleep(0.01)
            with self._spi_device as spi:
                spi.readinto(self._buf_rx)

            # Read the message envelope and contents
            msgtype, rspid, rsplen = struct.unpack('>BHB', self._buf_rx)
            if rsplen >= 16:
                rsp += self._buf_rx[4:20]
            else:
                rsp += self._buf_rx[4:rsplen+4]
            if self._debug:
                print("Reading: ", [hex(b) for b in self._buf_rx])

        # Clean up the response buffer
        if self._debug:
            print(rsp)

        return msgtype, rspid, rsp

    def init(self):
        """
        Sends the SDEP initialize command, which causes the board to reset.
        This command should complete in under 1s.
        """
        # Construct the SDEP packet
        struct.pack_into("<BHB", self._buf_tx, 0,
                         MsgType.COMMAND, SDEPCommand.INITIALIZE, 0)
        if self._debug:
            print("Writing: ", [hex(b) for b in self._buf_tx])

        # Send out the SPI bus
        with self._spi_device as spi:
            spi.write(self._buf_tx, end=4)

        # Wait 1 second for the command to complete.
        time.sleep(1)

    def uarttx(self, txt):
        """
        Sends the specific string out over BLE UART.
        :param txt: The new-line terminated string to send.
        """
        return self._cmd("AT+BLEUARTTX="+txt+"\n")

    def uartrx(self):
        """
        Reads data from the BLE UART FIFO.
        """
        return self._cmd("AT+BLEUARTRX\n")

    def command(self, string):
        try:
            msgtype, msgid, rsp = self._cmd(string+"\n")
            if msgtype == MsgType.ERROR:
                raise RuntimeError("Error (id:{0})".format(hex(msgid)))
            if msgtype == MsgType.RESPONSE:
                return rsp
        except RuntimeError as error:
            raise RuntimeError("AT command failure: " + repr(error))

    def command_check_OK(self, string, delay=0.0):
        ret = self.command(string)
        time.sleep(delay)
        if not ret or not ret[-4:]:
            raise RuntimeError("Not OK")
        if ret[-4:] != b'OK\r\n':
            raise RuntimeError("Not OK")
        if ret[:-4]:
            return str(ret[:-4], 'utf-8')