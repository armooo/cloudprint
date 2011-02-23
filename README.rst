Share your CUPS printers with google's cloud print.
Works with linux and OS X.

Requires
---------------------------------------------------
python 2.6 or 2.7
pycups (can be tricky on OS X)

Usage
---------------------------------------------------

::

  cloudprint [-d] [-p pid_file] [-h]
  -d              : enable daemon mode (requires the daemon module)
  -p pid_file     : path to write the pid to (default cloudprint.pid)
  -h              : display this help

Example
---------------------------------------------------

::

  cloudprint
  Google username: username@gmail.com
  Password:
  Added Printer Brother-HL-2170W

Install
---------------------------------------------------

::

  pip install cloudprint
