from __future__ import annotations
import importlib
import sys
import unittest


class FakeWin:
    def __init__(self, h, w, y, x):
        self.h, self.w, self.y, self.x = h, w, y, x

    def erase(self):
        pass

    def box(self):
        pass

    def addstr(self, *a, **k):
        pass

    def noutrefresh(self):
        pass

    def keypad(self, on):
        pass

    def scrollok(self, on):
        pass

    def getch(self):
        if FakeCurses._q:
            return FakeCurses._q.pop(0)
        return -1

    def get_wch(self):
        if FakeCurses._q:
            c = FakeCurses._q.pop(0)
            if isinstance(c, str):
                return c
            return c
        return -1

    def getmaxyx(self):
        return self.h, self.w


class FakeCurses:
    _q = []
    KEY_ENTER = 999
    KEY_BACKSPACE = 900
    KEY_UP = 998
    KEY_DOWN = 997
    A_BOLD = 1
    COLOR_CYAN = 1
    COLOR_GREEN = 2
    COLOR_YELLOW = 3
    COLOR_RED = 4
    COLOR_WHITE = 5
    error = Exception

    @staticmethod
    def newwin(nlines, ncols, begin_y, begin_x):
        return FakeWin(nlines, ncols, begin_y, begin_x)

    @staticmethod
    def wrapper(func, *a):
        return func(FakeWin(24, 80, 0, 0), *a)

    @staticmethod
    def doupdate():
        pass

    @staticmethod
    def start_color():
        pass

    @staticmethod
    def use_default_colors():
        pass

    @staticmethod
    def init_pair(*a):
        pass

    @staticmethod
    def color_pair(n):
        return 0


class TestTUI(unittest.TestCase):
    def test_session(self):
        sys.modules["curses"] = FakeCurses
        from agent import channels as ch
        importlib.reload(ch)
        TUIChannel = ch.TUIChannel

        class FakeP:
            model = "fake"

            def complete(self, messages, tools=None, stream=False):
                return {"choices": [{"message": {"role": "assistant", "content": "ответ"}}]}

            def count_tokens(self, t):
                return len(t) // 4

        from agent.config import AgentConfig
        from agent.core import Agent
        agent = Agent(AgentConfig(workspace="/tmp", mode="full-auto"))
        agent.provider = FakeP()

        FakeCurses._q = ["h", "i", 10,
                         "/", "e", "x", "i", "t", 10]
        tui = TUIChannel()
        tui.run_session(agent)
        self.assertIn("you> hi", tui.lines)
        self.assertIn("agent> ответ", tui.lines)

    def test_cyrillic_and_ctrl_d(self):
        sys.modules["curses"] = FakeCurses
        from agent import channels as ch
        importlib.reload(ch)
        TUIChannel = ch.TUIChannel

        class FakeP:
            model = "fake"

            def complete(self, messages, tools=None, stream=False):
                return {"choices": [{"message": {"role": "assistant", "content": "привет"}}]}

            def count_tokens(self, t):
                return len(t) // 4

        from agent.config import AgentConfig
        from agent.core import Agent
        agent = Agent(AgentConfig(workspace="/tmp", mode="full-auto"))
        agent.provider = FakeP()

        FakeCurses._q = ["п", "р", "и", "в", "е", "т", 10, FakeCurses.KEY_UP, 10, 4]
        tui = TUIChannel()
        tui.run_session(agent)
        self.assertIn("you> привет", tui.lines)
        self.assertIn("agent> привет", tui.lines)
        self.assertIn("you> привет", tui.lines[2:])


if __name__ == "__main__":
    unittest.main()
