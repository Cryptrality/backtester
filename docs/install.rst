.. index:: Get started

Get started
===========

Requirements
____________

*Cryptrality* is wrapped in a python package.
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

   pip install git+https://git@github.com/Cryptrality/backtester.git


Conda environment:
------------------

.. code-block:: yaml

    name: cryptrality
    channels:
      - conda-forge
      - defaults
    dependencies:
      - python=3.8
      - ta-lib
      - sphinxcontrib-programoutput
      - sphinx_rtd_theme
      - pip:
        - "--editable=git+https://git@github.com/Cryptrality/backtester.git@main#egg=cryptrality"


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


Example Run
____________


This is an Test run with a simple EMA cross RSI example strategy: 

.. command-output:: cryptrality backtest -s 22-1-22 -e 25-1-22 ../example_strategies/multi_symbols_ema_rsi.py
  :returncode: 0
  :shell:

This is another example run with a more complex strategy provided in the examples

.. command-output:: cryptrality backtest -s 22-1-22 -e 25-1-22 ../example_strategies/bayes_bollinger_multicoins_cooldown.py
  :returncode: 0
  :shell:

.. _virtualenv: https://virtualenv.pypa.io
.. _talib: https://mrjbq7.github.io/ta-lib/install.html
