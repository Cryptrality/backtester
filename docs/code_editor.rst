.. index:: Adjust from Trality code

Adjust from Trality code
===========

Requirements
____________

*Cryptrality* aims to be fully compatible with strategy written for the
*Trality* code editor.
However, there are currently a number of adjustments required to run a
strategy from the web-based code editor into this command line tool:

1. The `data` in cryptrality is not constructed similarly as in trality,
  instead, it's just a dictionary with "open", "close", "high", "low" keys,
  containing `numpy` arrays
2. The portfolio balance is missing, so a strategy that takes amounts from a
   percentage of the portfolio, might need to be adjusted to use a fix amount,
   until the portfolio balance is implemented
3. The plotting setup is completely different than in Trality, so until it's
   implemented to be compatible with trality syntax it will be conflicting with
   any plot setup for the code-editor
4. The context manager for the order `OrderScope` is also missing. Until I figure
   out how to implement it, the stop loss/take profit limits must be cancelled
   manually once one of the two is filled
5. The engine was first develop to test strategies in the futures market, so it's
   possible to short sell in the strategy, it's up to you check if by error you use
   this approach also in the spot market (which is not possible)
6. Many other things (please share things to add in the TODO), but all in all,
   I think is relatively easy to port trality strategies in few steps




