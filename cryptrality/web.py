import os
from flask import Flask, render_template, make_response, jsonify
from flask_httpauth import HTTPBasicAuth
from gevent.pywsgi import WSGIServer
from datetime import datetime
from cryptrality.misc import get_last_lines

import pandas as pd
import cryptrality.plotly


class web:
    def __init__(
        self,
        runner,
        mode="test",
        port=5050,
        static_username="alba",
        static_password="calidris",
    ) -> None:
        self.mode = mode
        app = Flask(__name__)
        auth = HTTPBasicAuth()
        self.app = app
        self.runner = runner
        self.port = port
        self.template_html = "index.html"

        @auth.get_password
        def get_password(username):
            if username == static_username:
                return static_password
            return None

        @auth.error_handler
        def unauthorized():
            return make_response(
                jsonify({"error": "Unauthorized access"}), 401
            )

        @app.route("/")
        def index():
            return render_template(self.template_html)

        @app.route("/api//trading_pairs/")
        @auth.login_required
        def trading_pairs():

            return jsonify(
                [{"symbol": symbol} for symbol in self.runner.trading_pairs]
            )

        @app.route("/api/logs/<string:log_type>/<int:n>")
        @auth.login_required
        def stream_logs(log_type=None, n=50):
            log_types = {
                "exec": "execution.log",
                "bot": "bot.log",
                "strategy": "strategy.log",
            }

            if log_type is None or log_type not in log_types:
                log_type = "bot"
            log_path = self.runner.log_path
            if log_path is None:
                return jsonify([])
            log_file = os.path.join(log_path, log_types[log_type])
            try:
                return jsonify(get_last_lines(log_file, n))
            except IOError:
                return jsonify([])

        @app.route("/api/callback/<string:symbol>/<string:time_window>")
        @auth.login_required
        def candlesticks(symbol, time_window):
            return self.last_data(symbol, time_window)

        @app.route("/api/summary")
        @auth.login_required
        def summary_perf():
            summary = self.summary_data()
            return jsonify(summary)

    def summary_data(self):
        positions = []
        all_pnl = []
        current_time = self.runner.current_time
        date_now = datetime.now()
        for symbol in self.runner.positions:
            for position in self.runner.positions[symbol]:
                orders = []
                for order in position.orders:
                    ord_data = {
                        "id": order.id,
                        "symbol": order.symbol,
                        "type": order.type.name,
                        "side": order.side.name,
                        "status": order.status.name,
                        "quantity": order.quantity,
                        "filled_quantity": order.filled_quantity,
                        "close_position": order.close_position,
                        "limit_price": order.limit_price,
                        "created_time": datetime.utcfromtimestamp(
                            order.created_time / 1000
                        ),
                        "executed_time": None,
                        "fees": order.fees,
                    }
                    if order.executed_time:
                        ord_data["executed_time"] = order.executed_time
                    orders.append(ord_data)
                if position.entry_time and position.exit_time:
                    pos_data = {
                        "symbol": position.symbol,
                        "entry_date": datetime.utcfromtimestamp(
                            position.entry_time / 1000
                        ),
                        "entry_price": position.price,
                        "exit_date": datetime.utcfromtimestamp(
                            position.exit_time / 1000
                        ),
                        "exit_price": position.exit_price,
                        "quantity": position.quantity,
                        "pnl": position.pnl,
                        "orders": orders,
                    }
                    all_pnl.append(
                        {"date": pos_data["exit_date"], "pnl": pos_data["pnl"]}
                    )
                elif position.entry_time:
                    pos_data = {
                        "symbol": position.symbol,
                        "entry_date": datetime.utcfromtimestamp(
                            position.entry_time / 1000
                        ),
                        "entry_price": position.price,
                        "exit_date": datetime.utcfromtimestamp(
                            current_time / 1000
                        ),
                        "exit_price": None,
                        "quantity": position.quantity,
                        "pnl": 0,
                        "orders": orders,
                    }
                elif position.exit_time:
                    pos_data = {
                        "symbol": position.symbol,
                        "entry_date": None,
                        "entry_price": position.price,
                        "exit_date": datetime.utcfromtimestamp(
                            position.exit_time / 1000
                        ),
                        "exit_price": position.exit_price,
                        "quantity": position.quantity,
                        "pnl": position.pnl,
                        "orders": orders,
                    }
                    all_pnl.append(
                        {"date": pos_data["exit_date"], "pnl": pos_data["pnl"]}
                    )
                else:
                    pos_data = {
                        "symbol": position.symbol,
                        "entry_date": None,
                        "entry_price": position.price,
                        "exit_date": None,
                        "exit_price": None,
                        "quantity": position.quantity,
                        "pnl": 0,
                        "orders": orders,
                    }
                positions.append(pos_data)
        if len(positions) > 0:
            min_entry_date = min(
                x["entry_date"]
                for x in positions
                if x["entry_date"] is not None
            )
            positions.sort(
                key=lambda x: x["entry_date"]
                if x["entry_date"]
                else min_entry_date
            )
        if len(all_pnl) > 0:
            all_pnl_df = pd.DataFrame(all_pnl)
            all_pnl_df.loc[:, "date"] = pd.to_datetime(
                all_pnl_df["date"], errors="coerce"
            )
            daily = all_pnl_df.resample("d", on="date").sum().dropna(how="all")
            total_pnl = daily["pnl"].sum()
            n_won = sum(all_pnl_df["pnl"] > 0)
            daily_pnl = {
                # "date": daily.index.date.tolist(),
                "date": [
                    str(date)
                    for date in [ts.date() for ts in daily.index.tolist()]
                ],
                "pnl": daily["pnl"].cumsum().tolist(),
            }
        else:
            daily_pnl = []
            n_won = 0
            total_pnl = 0
        return {
            "loaded_date": date_now,
            "positions": positions,
            "number_trades": len(all_pnl),
            "number_winnings": n_won,
            "total_pnl": total_pnl,
            "daily_pnl": daily_pnl,
        }

    def last_data(self, symbol=None, time_window=None):
        orders = []
        positions = []
        if symbol and symbol in self.runner.positions:
            for position in self.runner.positions[symbol]:
                for order in position.orders:
                    ord_data = {
                        "id": order.id,
                        "symbol": order.symbol,
                        "type": order.type,
                        "side": order.side,
                        "status": order.status,
                        "quantity": order.quantity,
                        "filled_quantity": order.filled_quantity,
                        "close_position": order.close_position,
                        "limit_price": order.limit_price,
                        "created_time": datetime.utcfromtimestamp(
                            order.created_time / 1000
                        ),
                        "executed_time": order.executed_time,
                        "fees": order.fees,
                    }
                    orders.append(ord_data)
                if position.exit_price:
                    pos_data = {
                        "symbol": position.symbol,
                        "entry_date": datetime.utcfromtimestamp(
                            position.entry_time / 1000
                        ),
                        "entry_price": position.price,
                        "exit_date": datetime.utcfromtimestamp(
                            position.exit_time / 1000
                        ),
                        "exit_price": position.exit_price,
                        "quantity": position.quantity,
                        "pnl": position.pnl,
                    }
                    positions.append(pos_data)
            if len(positions) > 0:
                position_df = pd.DataFrame(positions)
            else:
                position_df = pd.DataFrame(
                    [
                        {
                            "symbol": symbol,
                            "entry_date": None,
                            "entry_price": None,
                            "exit_date": None,
                            "exit_price": None,
                            "quantity": None,
                            "pnl": None,
                        }
                    ]
                )
            if len(self.runner.plot_data[symbol]) > 0:
                plot_data = pd.DataFrame(self.runner.plot_data[symbol])
                merged_data = simplebot.plotly.merge_plot_trades(
                    plot_data, position_df
                )
                g = merged_data["data_frame"].groupby(
                    pd.Grouper(freq=time_window)
                )
                groups = list(g.groups.keys())

                df_temp = g.get_group(groups[-1])

                fig = simplebot.plotly.strategy_figure(
                    df_temp,
                    symbol,
                    self.runner.plot_config,
                    merged_data["extra_data"],
                )
                return fig.to_json()
            else:
                return {}
        return {}

    def start(self):
        if self.mode == "production":
            http_server = WSGIServer(("", self.port), self.app)
            http_server.serve_forever()
        else:
            self.app.run(host="0.0.0.0", port=self.port)
