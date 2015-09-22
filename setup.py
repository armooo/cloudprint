try:
    from setuptools import setup, find_packages
except ImportError:
    from ez_setup import use_setuptools
    use_setuptools()
    from setuptools import setup, find_packages

setup(
    name='cloudprint',
    version='0.14',
    description='Google cloud print proxy for linux/OSX',
    long_description=open('README.rst').read(),
    author='Jason Michalski',
    author_email='armooo@armooo.net',
    url='https://github.com/armooo/cloudprint',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Intended Audience :: End Users/Desktop',
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: POSIX',
        'Topic :: Printing',
        'License :: OSI Approved :: GNU General Public License (GPL)',
    ],
    packages=find_packages(exclude=['ez_setup']),
    entry_points={
        'console_scripts': [
            'cloudprint = cloudprint.cloudprint:main',
        ],
    },
    install_requires=[
        'configargparse',
        'pycups',
        'requests >= 2.7.0',
    ],
    extras_require={
        'daemon': ['python-daemon >= 2.0.0'],
    },
)
