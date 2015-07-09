Share your CUPS printers with google's cloud print.
Works with linux and OS X.

This software is a python implementation of a cloud print connector. Unlike
Google's linux connector, it does not require chrome to be installed on the server.


Requires
---------------------------------------------------
- python 2.6 or 2.7
- pycups (can be tricky on OS X) wich depends on libcups2-dev

Usage
---------------------------------------------------

::

  cloudprint [<option> ...]
  -d              : enable daemon mode (requires the daemon module)
  -l              : logout of the current google account
  -p pid_file     : path to write the pid to (default cloudprint.pid)
  -a account_file : path to google account ident data (optional)
  -c              : establish and store login credentials, then exit
  -f              : 'fast poll', if notifications aren't working
  -u              : store username/password in addition to login token
                    to avoid authentication expiration
  -i regexp       : include files matching regexp
  -x regexp       : exclude filees matching regexp
                    regexp: a Python regexp, which is matched against the
                            start of the printer name
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

Examples - Include/Exclude
---------------------------------------------------

Include only the printers "`lp`" and "`2up`":
::

  cloudprint -i lp -i 2up

Exclude all printers whose names start with "`GCP-`":
::

  cloudprint -x GCP-

By default, all printers are included.  For the include and exclude options,
the argument is a regular expression which is matched against the start of the
printer name.

For example, to include all printers whose names begin "`lp`":
::

  cloudprint -i lp # includes both lp and lp2up


Install
---------------------------------------------------

::

  pip install cloudprint
  or with optional daemon support
  pip install cloudprint[daemon]

After running cloudprint, verify that the connector successfully installed the cloud printer by visiting
http://www.google.com/cloudprint/manage.html.
