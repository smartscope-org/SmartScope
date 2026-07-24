import plotly.graph_objs as go


def apply_default_style(fig, title_flag=False):
    top_margin = 60 if title_flag else 30
    fig.update_layout(
        showlegend=True,
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.005,
            xanchor='center',
            x=0.5,
        ),
        margin={"b": 40, "l": 60, "r": 30, "t": top_margin},
        plot_bgcolor="white",
        xaxis=dict(
                linecolor='black',
                linewidth=0.75,
                mirror=True, 
                showgrid=True,
                gridcolor='lightgrey',
                griddash='dot', 
                ticks='inside',
                ticklen=2,
                tickwidth=0.75,
                tickcolor='black',
            ),
        yaxis=dict(
                linecolor='black',
                linewidth=0.75,
                mirror=True, 
                showgrid=True,
                gridcolor='lightgrey',
                griddash='dot', 
                ticks='inside',
                ticklen=2,
                tickwidth=0.75,
                tickcolor='black',
                title_standoff=10,
                automargin=False,
            ),
    )
    return fig


def plot_histogram(vals: list, filter_thr: int, title: str, xname: str):

    all_data = list(map(lambda x: filter_thr if x > filter_thr else x, vals))
    latest_data = all_data[-100:]
    hist_all = go.Histogram(x=all_data, nbinsx=30, name='All')
    hist_latest = go.Histogram(x=latest_data, nbinsx=30, name='Latest 100')
    layout = go.Layout(title=title,
                        xaxis=dict(title=xname,),
                        yaxis=dict(title='Number of exposures',)
                        )
    fig = apply_default_style(go.Figure(data=[hist_all,hist_latest], layout=layout), True)
    graph = fig.to_html(full_html=False)
    return graph