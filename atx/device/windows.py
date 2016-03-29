#-*- encoding: utf-8 -*-
"""
Windows application as a device
"""

from __future__ import absolute_import

import os
import time
import struct
import win32con
import win32api
import win32gui
import win32process
import ctypes
from  ctypes import wintypes, windll 
from PIL import Image
from collections import namedtuple

from atx.device import Bounds, Display
from atx.device.device_mixin import DeviceMixin
from atx.errors import WindowsAppNotFoundError

# https://msdn.microsoft.com/en-us/library/windows/desktop/dd183376(v=vs.85).aspx
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', wintypes.DWORD),
        ('biWidth', wintypes.LONG),
        ('biHeight', wintypes.LONG),
        ('biPlanes', wintypes.WORD),
        ('biBitCount', wintypes.WORD),
        ('biCompression', wintypes.DWORD),
        ('biSizeImage', wintypes.DWORD),
        ('biXPelsPerMeter', wintypes.LONG),
        ('biYPelsPerMeter', wintypes.LONG),
        ('biClrUsed', wintypes.DWORD),
        ('biClrImportant', wintypes.DWORD)
    ]

def find_process_id(exe_file):
    exe_file = os.path.normpath(exe_file).lower()
    command = "wmic process get processid,commandline"
    for line in os.popen(command).read().lower().splitlines():
        line = line.strip()
        if not line:
            continue
        line = line.split()
        pid = line[-1]
        cmd = " ".join(line[:-1])
        if not cmd:
            continue
        elif cmd.startswith("'") or cmd.startswith('"'):
            pos = cmd.find(cmd[0], 1)
            cmd = cmd[1:pos]
        else:
            cmd = cmd.split()[0]

        if exe_file == cmd:
            return int(pid)

Rect = namedtuple('Rect', ('left', 'top', 'right', 'bottom'))
Position = namedtuple('Position', ('left', 'top', 'width', 'height'))

class Window(object):
    """A interface of windows' window display zone.

    Args:
        window_name: the text on window border 
        exe_file: the path to windows executable
        exclude_border: count the border in display zone or not. 
            Default is True.

    Attributes:
        screen: a PIL Image object of current display zone.
        rect: (left, top, right, bottom) of the display zone.
        screen_position: (offsetx, offsety, width, height) of the screen, offsets are 
            relative to the window's Rect got by win32gui.GetWindowRect

    """

    def __init__(self, window_name=None, exe_file=None, exclude_border=True):
        hwnd = 0

        # first check window_name
        if window_name is not None:
            hwnd = win32gui.FindWindow(None, window_name)
            if hwnd == 0:
                def callback(h, extra):
                    if window_name in win32gui.GetWindowText(h):
                        extra.append(h)
                    return True
                extra = []
                win32gui.EnumWindows(callback, extra)
                if extra: hwnd = extra[0]
            if hwnd == 0:
                raise WindowsAppNotFoundError("Windows Application <%s> not found!" % window_name)

        # check exe_file by checking all processes current running.
        elif exe_file is not None:
            pid = find_process_id(exe_file)
            if pid is not None:
                def callback(h, extra):
                    if win32gui.IsWindowVisible(h) and win32gui.IsWindowEnabled(h):
                        _, p = win32process.GetWindowThreadProcessId(h)
                        if p == pid:
                            extra.append(h)
                        return True
                    return True
                extra = []
                win32gui.EnumWindows(callback, extra)
                #TODO: get main window from all windows.
                if extra: hwnd = extra[0]
            if hwnd == 0:
                raise WindowsAppNotFoundError("Windows Application <%s> is not running!" % exe_file)

        # if window_name & exe_file both are None, use the screen.
        if hwnd == 0:
            hwnd = win32gui.GetDesktopWindow()

        self.hwnd = hwnd
        self.exclude_border = exclude_border

    @property
    def rect(self):
        if not self.exclude_border:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        else:
            _left, _top, _right, _bottom = win32gui.GetClientRect(hwnd)
            left, top = win32gui.ClientToScreen(hwnd, (_left, _top))
            right, bottom = win32gui.ClientToScreen(hwnd, (_right, _bottom))
        return Rect(left, top, right, bottom)

    @property
    def screen_position(self):
        hwnd = self.hwnd
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        if self.exclude_border:
            _left, _top, _right, _bottom = win32gui.GetClientRect(hwnd)
            _left, _top = win32gui.ClientToScreen(hwnd, (_left, _top))
            _right, _bottom = win32gui.ClientToScreen(hwnd, (_right, _bottom))
            width, height = _right-_left, _bottom-_top
            x, y = _left-left, _top-top
        else:
            width, height = right-left, bottom-top
            x, y = 0, 0
        return Position(x, y, width, height)

    @property
    def screen(self):
        """PIL Image of current window screen.
        reference: https://msdn.microsoft.com/en-us/library/dd183402(v=vs.85).aspx"""
        hwnd = self.hwnd

        # get screen size and offset
        x, y, width, height = self.screen_position

        # the device context of the window 
        hdcwin = win32gui.GetWindowDC(hwnd)
        # make a temporary dc
        hdcmem = win32gui.CreateCompatibleDC(hdcwin)
        # make a temporary bitmap in memory, this is a PyHANDLE object
        hbmp = win32gui.CreateCompatibleBitmap(hdcwin, width, height)
        # select bitmap for temporary dc
        win32gui.SelectObject(hdcmem, hbmp)
        # copy bits to temporary dc
        win32gui.BitBlt(hdcmem, 0, 0, width, height, 
                        hdcwin, x, y, win32con.SRCCOPY)
        # check the bitmap object infomation
        bmp = win32gui.GetObject(hbmp)

        bi = BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.biWidth = bmp.bmWidth
        bi.biHeight = bmp.bmHeight
        bi.biPlanes = bmp.bmPlanes
        bi.biBitCount = bmp.bmBitsPixel
        bi.biCompression = 0 # BI_RGB
        bi.biSizeImage = 0
        bi.biXPelsPerMeter = 0
        bi.biYPelsPerMeter = 0
        bi.biClrUsed = 0
        bi.biClrImportant = 0

        # calculate total size for bits
        pixel = bmp.bmBitsPixel
        size = ((bmp.bmWidth * pixel + pixel - 1)/pixel) * 4 * bmp.bmHeight
        buf = (ctypes.c_char * size)()

        # read bits into buffer
        windll.gdi32.GetDIBits(hdcmem, hbmp.handle, 0, bmp.bmHeight, buf, ctypes.byref(bi), win32con.DIB_RGB_COLORS)

        # make a PIL Image
        img = Image.frombuffer('RGB', (bmp.bmWidth, bmp.bmHeight), buf, 'raw', 'BGRX', 0, 1)
        img = img.transpose(Image.FLIP_TOP_BOTTOM)

        # cleanup
        win32gui.DeleteObject(hbmp)
        win32gui.DeleteObject(hdcmem)
        win32gui.ReleaseDC(self.hwnd, hdcwin)

        return img

    def _screenshot(self, filepath):
        dirpath = os.path.dirname(os.path.abspath(filepath))
        if not os.path.exists(dirpath):
            os.makedirs(dirpath)
        self.screen.save(filepath)

class FrozenWindow(Window):
    """Non-resizable Window, use lots of cached properties"""

    def __init__(self, *args, **kwargs):
        Window.__init__(self, *args, **kwargs)
        self.__init_rect_position()
        self.__init_screen_handles()

    def __init_rect_position(self):
        hwnd = self.hwnd
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        if self.exclude_border:
            _left, _top, _right, _bottom = win32gui.GetClientRect(hwnd)
            _left, _top = win32gui.ClientToScreen(hwnd, (_left, _top))
            _right, _bottom = win32gui.ClientToScreen(hwnd, (_right, _bottom))
            width, height = _right-_left, _bottom-_top
            x, y = _left-left, _top-top
            self._rect = Rect(_left, _top, _right, _bottom)
            self._screen_position = Position(x, y, width, height)
        else:
            width, height = right-left, bottom-top
            x, y = 0, 0
            self._rect = Rect(left, top, right, bottom)
            self._screen_position = Position(x, y, width, height)

    @property 
    def rect(self):
        return self._rect

    @property 
    def screen_position(self):
        return self._screen_position

    def __init_screen_handles(self):
        hwnd = self.hwnd
        # get screen size and offset
        x, y, width, height = self.screen_position
        # the device context of the window 
        hdcwin = win32gui.GetWindowDC(hwnd)
        # make a temporary dc
        hdcmem = win32gui.CreateCompatibleDC(hdcwin)
        # make a temporary bitmap in memory, this is a PyHANDLE object
        hbmp = win32gui.CreateCompatibleBitmap(hdcwin, width, height)
        # select bitmap for temporary dc
        win32gui.SelectObject(hdcmem, hbmp)
        # check the bitmap object infomation
        bmp = win32gui.GetObject(hbmp)
        bi = BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.biWidth = bmp.bmWidth
        bi.biHeight = bmp.bmHeight
        bi.biPlanes = bmp.bmPlanes
        bi.biBitCount = bmp.bmBitsPixel
        bi.biCompression = 0 # BI_RGB
        bi.biSizeImage = 0
        bi.biXPelsPerMeter = 0
        bi.biYPelsPerMeter = 0
        bi.biClrUsed = 0
        bi.biClrImportant = 0
        # calculate total size for bits
        pixel = bmp.bmBitsPixel
        size = ((bmp.bmWidth * pixel + pixel - 1)/pixel) * 4 * bmp.bmHeight
        buf = (ctypes.c_char * size)()

        self._hdcwin = hdcwin
        self._hdcmem = hdcmem
        self._bi = bi
        self._hbmp = hbmp
        self._buf = buf

    @property
    def screen(self):
        """PIL Image of current window screen.
        reference: https://msdn.microsoft.com/en-us/library/dd183402(v=vs.85).aspx"""
        hwnd = self.hwnd
        x, y, width, height = self.screen_position
        # copy bits to temporary dc
        win32gui.BitBlt(self._hdcmem, 0, 0, width, height, 
                        self._hdcwin, x, y, win32con.SRCCOPY)
        # read bits into buffer
        windll.gdi32.GetDIBits(self._hdcmem, self._hbmp.handle, 0, height, self._buf, ctypes.byref(self._bi), win32con.DIB_RGB_COLORS)
        # make a PIL Image
        img = Image.frombuffer('RGB', (width, height), self._buf, 'raw', 'BGRX', 0, 1)
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
        return img

    def __del__(self):
        # cleanup
        win32gui.DeleteObject(self._hbmp)
        win32gui.DeleteObject(self._hdcmem)
        win32gui.ReleaseDC(self.hwnd, self._hdcwin)

class WindowsDevice(Window, DeviceMixin):
    def __init__(self, **kwargs):
        DeviceMixin.__init__(self)
        Window.__init__(self, **kwargs)

    def screenshot(self, filename=None):
        """Take screen snapshot

        Args:
            filename: filename where save to, optional

        Returns:
            PIL.Image object

        Raises:
            TypeError, IOError
        """
        if filename:
            self._screenshot(filename)
        return self.screen

    def click(self, x, y):
        """Simulate click within window screen.

        Args:
            x, y: int, pixel distance from window (left, top) as origin

        Returns:
            None
        """

    def text(self, text):
        """Simulate text input to window.

        Args:
            text: string

        Returns:
            None
        """

    @property
    def display(self):
        """Display size in pixels."""
        _, _, w, h = self.screen_position
        return Display(w, h)