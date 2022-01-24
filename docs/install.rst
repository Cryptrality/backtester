.. index:: Get started

Get started
===========

Requirements
____________

*simple)bot* is wrapped in a python package.
So `Python` is required to use the software. Only Python3 (Python >= 3.4)
is supported.

The library also depends on the `talib`_ C++ headers to be installed in the system

Installation
____________

.. note::
   It is strongly advised to use `virtualenv`_ to install the module locally.


From git with pip:
------------------

.. code-block:: bash

   pip install git+ssh://git@github.com/Cryptrality/backtester.git/


After installation the `cryptrality` command line allows access to various modules:

.. command-output:: cryptrality
  :returncode: 0
  :shell:

Using the `backtest` sub-command

.. command-output:: cryptrality backtest
  :returncode: 2
  :shell:


Using the `download_year` sub-command

.. command-output:: cryptrality download_year
  :returncode: 2
  :shell:



.. _virtualenv: https://virtualenv.pypa.io
.. _talib: https://mrjbq7.github.io/ta-lib/install.html
