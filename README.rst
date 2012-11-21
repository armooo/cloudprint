Share your CUPS printers with google's cloud print.
Works with linux and OS X.

Requires
---------------------------------------------------
python 2.6 or 2.7
pycups (can be tricky on OS X)

Usage
---------------------------------------------------

::

  cloudprint [-d] [-p pid_file] [-a account_file] [-h]
  -d              : enable daemon mode (requires the daemon module)
  -l              : logout of the current google account
  -p pid_file     : path to write the pid to (default cloudprint.pid)
  -a account_file : path to google account ident data (optional)
                    account_file format:  <Google username>
                                          <Google password>
  -h              : display this help

Google accounts with 2 step verification enabled need to use an
`application-specific password <http://www.google.com/support/accounts/bin/static.py?page=guide.cs&guide=1056283&topic=1056286>`_.

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
