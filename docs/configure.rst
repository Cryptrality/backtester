.. index:: Configuration

.. _configuration:

Configuration
=============

There are various aspect of the framework that can be configured.

The configuration can be passed as environment variable or set in
a local configuration file

The set of configuration variables are listed in the section
"`Available variables`_"

Local configuration file
________________________


When a configuration file in the current working directory names
`bot.config` exists, the program will read the configuration to set the variables.


The configuration file looks like this:

.. code-block:: bash
   
   SLIPPAGE = 0.0008
   FEES = 0.001
   CACHED_KLINES_PATH = cached_klines
   INITIAL_BALANCE = 1000


Environment variable
____________________


Variables can also be set as environment variables.
Setting a variable in the environment will override the corresponding
variable if also set in the configuration file.


Available variables
___________________


.. list-table::
   :widths: 33 66
   :header-rows: 1

   * - Variable
     - Description
   * - CACHED_KLINES_PATH
     - Sets the path of saved historical data.
   * - INITIAL_BALANCE
     - Set the initial capital during backtesting.
   * - FEES
     - Defines the percentage of fees omn the order amount to account for during backtesting.
   * - SLIPPAGE
     - Defines the average slippage during backtesting (slippage is not calculated yet, dummy variable for now).
