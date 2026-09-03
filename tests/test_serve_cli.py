"""Where `serve` binds, and why the default is a contract rather than a taste.

This app has no authentication. That is a stated design position, not an
omission — but it only holds together because the port is somewhere nobody
else can reach, and so the bind address is load-bearing in a way a mere
default usually is not. `--host` exists because a container cannot use
127.0.0.1 (there it is the container's own loopback, and a published port
reaches nothing), and the flag would be a bad trade if adding it quietly
widened the bind for everybody who never passes it.

So both halves are pinned here: the default must stay loopback, so exposure
is always something a person typed, and the value passed must actually reach
uvicorn, so an operator who typed one is not silently served a narrower app
than the one they asked for. The second is the half worth testing carefully —
a flag can parse perfectly and still be dropped at the call site, which is
exactly what the hardcoded `host="127.0.0.1"` this replaced would have done
to it.

The exercise goes through `main` rather than a parser fixture on purpose.
The claim being defended is about what `python -m curricle serve` does, and
a test of an extracted helper would keep passing if the dispatch stopped
using it.
"""

import contextlib
import io
import unittest
from unittest import mock

from curricle.__main__ import main


class ServeBind(unittest.TestCase):
    def served_with(self, *argv) -> dict:
        """Run `serve` with the app and the server both stubbed, and report
        the keyword arguments uvicorn was actually handed."""
        with mock.patch("uvicorn.run") as run, \
             mock.patch("curricle.webapp.create_app", return_value=object()), \
             mock.patch("curricle.coursehome.maybe_courses_dir",
                        return_value=None), \
             contextlib.redirect_stdout(io.StringIO()):
            main(["serve", "--tenant", "you", *argv])
        self.assertEqual(run.call_count, 1)
        return run.call_args.kwargs

    def test_the_default_bind_is_loopback(self):
        self.assertEqual(self.served_with()["host"], "127.0.0.1")

    def test_a_widened_bind_is_the_one_used(self):
        got = self.served_with("--host", "0.0.0.0")
        self.assertEqual(got["host"], "0.0.0.0")

    def test_the_port_still_travels_with_it(self):
        got = self.served_with("--host", "0.0.0.0", "--port", "9999")
        self.assertEqual((got["host"], got["port"]), ("0.0.0.0", 9999))


if __name__ == "__main__":
    unittest.main()
