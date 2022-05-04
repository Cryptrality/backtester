import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pandas.core.frame import DataFrame
from pandas.core.indexes.base import Index
from plotly.graph_objs._figure import Figure
from typing import Dict, List, Union


def strategy_figure(df_i: DataFrame, symbol: str, config: Dict[str, Dict[str, str]], extra_data: Index) -> Figure:
    entry = df_i[["Date", "entry_price"]].dropna()
    exit = df_i[["Date", "exit_price"]].dropna()

    subplots_list = get_subplots_list(config)

    unit_width = 1 / (len(subplots_list) + 4)
    y_space = 1 / (len(subplots_list)) / len(subplots_list)
    slider_height = y_space / 2

    init_subplots_specs = [
        [{"secondary_y": True}],
        [{"secondary_y": False}],
    ]
    init_row_width = [
        (3 * unit_width) - (slider_height * 2),
        1 * unit_width,
    ]
    for subplot_panel in subplots_list:
        if subplot_panel != "root":
            init_subplots_specs.append([{"secondary_y": False}])
            init_row_width.append(1 * unit_width)
    init_row_width.reverse()
    fig = make_subplots(
        rows=len(subplots_list) + 1,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=y_space,
        row_width=init_row_width,
        specs=init_subplots_specs,
    )

    fig.add_trace(
        go.Candlestick(
            x=df_i["Date"],
            open=df_i["open"],
            high=df_i["high"],
            low=df_i["low"],
            close=df_i["close"],
            name=symbol,
            opacity=1,
            increasing_fillcolor="#24A06B",
            decreasing_fillcolor="#CC2E3C",
            increasing_line_color="#2EC886",
            decreasing_line_color="#FF3A4C",
        ),
        secondary_y=True,
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Candlestick(
            x=df_i["Date"],
            open=df_i["open"],
            high=df_i["high"],
            low=df_i["low"],
            close=df_i["close"],
            name=symbol,
            opacity=1,
            increasing_fillcolor="#24A06B",
            decreasing_fillcolor="#CC2E3C",
            increasing_line_color="#2EC886",
            decreasing_line_color="#FF3A4C",
            visible=False,
        ),
        secondary_y=False,
        row=1,
        col=1,
    )
    ymin = df_i["low"].min()
    ymax = df_i["high"].max()
    for extra_plot in config.keys():
        if extra_plot not in extra_data:
            continue
        if config[extra_plot]["plot"] != "root":
            continue
        plot_config = config[extra_plot]
        if plot_config["type"] == "area":
            fig.add_trace(
                go.Scatter(
                    x=df_i["Date"],
                    y=df_i[plot_config["upper"]],
                    name=plot_config["upper"],
                    line={"dash": "dash"},
                    line_color=plot_config["color"],
                    opacity=0.5,
                ),
                secondary_y=False,
                row=1,
                col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=df_i["Date"],
                    y=df_i[plot_config["lower"]],
                    name=plot_config["lower"],
                    line={"dash": "dash"},
                    fill="tonexty",
                    line_color=plot_config["color"],
                    opacity=0,
                ),
                secondary_y=False,
                row=1,
                col=1,
            )
            if ymin > df_i[plot_config["lower"]].min():
                ymin = df_i[plot_config["lower"]].min()
            if ymax < df_i[plot_config["upper"]].max():
                ymax = df_i[plot_config["upper"]].max()
        elif plot_config["type"] == "line":
            fig.add_trace(
                go.Scatter(
                    x=df_i["Date"],
                    y=df_i[extra_plot],
                    mode="lines",
                    name=extra_plot,
                    line=dict(color=plot_config["color"], width=1),
                ),
                secondary_y=True,
                row=1,
                col=1,
            )
            if ymin > df_i[extra_plot].min():
                ymin = df_i[extra_plot].min()
            if ymax < df_i[extra_plot].max():
                ymax = df_i[extra_plot].max()

    fig.add_trace(
        go.Scatter(
            x=entry["Date"],
            y=entry["entry_price"],
            name="entry",
            mode="markers+text",
            text="▲",
        ),
        secondary_y=True,
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=exit["Date"],
            y=exit["exit_price"],
            name="exit",
            mode="markers+text",
            text="▼",
        ),
        secondary_y=True,
        row=1,
        col=1,
    )
    tile_title = "%s %s" % (
        symbol,
        " ".join(
            list(
                map(
                    str,
                    [
                        df_i["Date"].min().strftime("%m/%d/%y-%H:%M"),
                        " - ",
                        df_i["Date"].max().strftime("%m/%d/%y-%H:%M"),
                    ],
                )
            )
        ),
    )
    fig.update_layout(title_text=tile_title)
    fig.update_layout(height=600)

    ymin = ymin - (0.02 * ymin)
    ymax = ymax + (0.02 * ymax)

    is_winning = df_i["close"] > df_i["open"]
    col_winning = ["#CC2E3C", "#24A06B"]
    line_col_winning = ["#FF3A4C", "#2EC886"]
    vol_col = [col_winning[i] for i in is_winning.astype(int).tolist()]
    vol_line_col = [
        line_col_winning[i] for i in is_winning.astype(int).tolist()
    ]
    fig.add_trace(
        go.Bar(
            x=df_i["Date"],
            y=df_i["volume"],
            name="volume",
            marker_color=vol_col,
            marker_line_color=vol_line_col,
            marker_line_width=2,
        ),
        row=2,
        col=1,
    )

    next_row = 3
    for subplot_panel in subplots_list:
        if subplot_panel == "root":
            continue
        for extra_plot in config.keys():
            if extra_plot not in extra_data:
                continue
            if config[extra_plot]["plot"] == subplot_panel:
                draw_extra_panel(df_i, fig, next_row, config, extra_plot)
        next_row += 1

    fig.update_xaxes(gridcolor="#1f292f", showgrid=True, fixedrange=True)
    fig.update_yaxes(
        range=[ymin, ymax],
        scaleanchor="y2",
        secondary_y=False,
        gridcolor="#1f292f",
        showgrid=True,
        row=1,
        col=1,
    )
    fig.update_yaxes(
        range=[ymin, ymax],
        scaleanchor="y",
        secondary_y=True,
        gridcolor="#1f292f",
        showgrid=True,
        row=1,
        col=1,
    )
    fig.update_xaxes(row=1, col=1, rangeslider_thickness=slider_height)
    for i in range(2, len(subplots_list) + 2):
        fig.update_yaxes(
            fixedrange=True,
            gridcolor="#1f292f",
            showgrid=True,
            row=i,
            col=1,
        )
    return fig


def merge_plot_trades(plot_df: DataFrame, trade_df: DataFrame) -> Dict[str, Union[Index, DataFrame]]:
    plot_df.loc[:, "timestamp"] = pd.to_datetime(
        plot_df["timestamp"] / 1000, unit="s"
    )
    plot_df.loc[:, "timestamp"] = plot_df.timestamp.dt.tz_localize("UTC")
    plot_df.loc[:, "Date"] = plot_df["timestamp"]
    if sum(trade_df.entry_date.notnull()) > 0:
        entry_i = trade_df.loc[
            trade_df.entry_date.notnull(), ["entry_date", "entry_price"]
        ]
        entry_i.loc[:, "entry_date"] = pd.to_datetime(entry_i["entry_date"])
        entry_i.loc[:, "entry_date"] = entry_i.entry_date.dt.tz_localize("UTC")
    else:
        entry_i = None
    if sum(trade_df.exit_date.notnull()) > 0:
        exit_i = trade_df.loc[
            trade_df.exit_date.notnull(), ["exit_date", "exit_price"]
        ]
        exit_i.loc[:, "exit_date"] = pd.to_datetime(exit_i["exit_date"])
        exit_i.loc[:, "exit_date"] = exit_i.exit_date.dt.tz_localize("UTC")
    else:
        exit_i = None
    # trade_df.loc[:, "entry_date"] = pd.to_datetime(trade_df["entry_date"])
    # trade_df.loc[:, "exit_date"] = pd.to_datetime(trade_df["exit_date"])
    # trade_df.loc[:, "entry_date"] = trade_df.entry_date.dt.tz_localize("UTC")
    # trade_df.loc[:, "exit_date"] = trade_df.exit_date.dt.tz_localize("UTC")
    # entry_i = trade_df[["entry_date", "entry_price"]].copy()
    # exit_i = trade_df[["exit_date", "exit_price"]].copy()

    plot_df.set_index("timestamp", inplace=True)
    if entry_i is None:
        df_t = plot_df.copy()
        df_t["entry_price"] = np.NaN
    else:
        entry_i.set_index("entry_date", inplace=True)
        df_t = plot_df.merge(
            entry_i, left_index=True, right_index=True, how="outer"
        )
    if exit_i is None:
        df_t["exit_price"] = np.NaN
    else:
        exit_i.set_index("exit_date", inplace=True)
        df_t = df_t.merge(
            exit_i, left_index=True, right_index=True, how="outer"
        )
    default_columns = [
        "open",
        "close",
        "high",
        "low",
        "volume",
        "buy_volume",
        "Date",
        "entry_price",
        "exit_price",
    ]
    extra_data = df_t.columns[~df_t.columns.isin(default_columns)]
    df_t = float_all_unprotected_columns(df_t, extra_data)
    return {"extra_data": extra_data, "data_frame": df_t}


def trade_charts(plot_df: DataFrame, trade_df: DataFrame, output_html: str, symbol: str, config: Dict[str, Dict[str, str]], freq: str="6h") -> None:

    merged_data = merge_plot_trades(plot_df, trade_df)
    df_t = merged_data["data_frame"]
    extra_data = merged_data["extra_data"]

    g = df_t.groupby(pd.Grouper(freq=freq))
    groups = list(g.groups.keys())
    fig_list = []

    for i in range(len(groups)):

        df_temp = g.get_group(groups[i])
        fig_i = strategy_figure(df_temp, symbol, config, extra_data)

        fig_list.append(fig_i)

    with open(output_html, "w") as dashboard:
        dashboard.write("<html><head></head><body>" + "\n")
        include_plotlyjs = True

        for fig in fig_list:
            inner_html = (
                fig.to_html(include_plotlyjs=include_plotlyjs)
                .split("<body>")[1]
                .split("</body>")[0]
            )
            dashboard.write(inner_html)
            include_plotlyjs = False
        dashboard.write("</body></html>" + "\n")


def float_all_unprotected_columns(df: DataFrame, col_names: Index) -> DataFrame:
    for col_name in col_names:
        df.loc[:, col_name].replace("None", np.nan, inplace=True)
        df.loc[:, col_name] = pd.to_numeric(df[col_name], downcast="float")
    return df


def get_subplots_list(config: Dict[str, Dict[str, str]]) -> List[str]:
    panels = []
    for plot_key in config:
        plot_data = config[plot_key]
        plot_space = plot_data["plot"]
        if plot_space not in panels:
            panels.append(plot_space)
    return panels


def draw_extra_panel(df: DataFrame, fig: Figure, n_row: int, config_data: Dict[str, Dict[str, str]], plot_key: str) -> None:

    plot_config = config_data[plot_key]
    if plot_config["type"] == "area":
        fig.add_trace(
            go.Scatter(
                x=df["Date"],
                y=df[plot_config["upper"]],
                name=plot_config["upper"],
                line={"dash": "dash"},
                line_color=plot_config["color"],
                opacity=0.5,
            ),
            row=n_row,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df["Date"],
                y=df[plot_config["lower"]],
                name=plot_config["lower"],
                line={"dash": "dash"},
                fill="tonexty",
                line_color=plot_config["color"],
                opacity=0,
            ),
            row=n_row,
            col=1,
        )
    elif plot_config["type"] == "line":
        fig.add_trace(
            go.Scatter(
                x=df["Date"],
                y=df[plot_key],
                mode="lines",
                name=plot_key,
                line=dict(color=plot_config["color"], width=1),
            ),
            row=n_row,
            col=1,
        )
    elif plot_config["type"] == "bar":
        fig.add_trace(
            go.Bar(
                x=df["Date"],
                y=df["volume"],
                name="volume",
                marker_color=plot_config["color"],
            ),
            row=n_row,
            col=1,
        )
