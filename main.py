import pandas as pd
from sqlalchemy import create_engine
import json
import locale
import pandas as pd
from datetime import date
from jinja2 import Template
from template import html_template

def format_date():
    today = date.today()
    try:
        locale.setlocale(locale.LC_TIME, 'en_US.UTF-8')
    except locale.Error:
        locale.setlocale(locale.LC_TIME, 'C')
    year = today.year
    month = str(today.month).zfill(2)
    day = str(today.day).zfill(2)
    weekday = today.strftime('%A')
    return f"{year}-{month}-{day} ({weekday})"

formatted_date = format_date()

driver = 'ODBC Driver 17for SQL Server'
server_name = 'HD'
database = 'CF'
engine = create_engine(f'mssql+pyodbc://{server_name}/{database}?driver=ODBC+Driver+17+for+SQL+Server', fast_executemany=True)
conn_sql = engine.raw_connection()

sql_query = """
with tb1 as (
SELECT 
    miesiac, 
    iloscZam, 
    [Ilosc dostarczona], 
    wartoscZAM, 
    WartoscPZ, 
    Logo_dost, 
    [Planowana data dostawy], 
    [data przyjecia],
    CASE 
        WHEN DATENAME(WEEKDAY, [Planowana data dostawy]) = 'Friday' THEN 
            CASE 
                WHEN [data przyjecia] <= DATEADD(DAY, 3, [Planowana data dostawy]) THEN 1.0
                ELSE 0
            END
        ELSE 
            CASE 
                WHEN [data przyjecia] <= DATEADD(DAY, 2, [Planowana data dostawy]) THEN 1.0
                ELSE 0
            END
    END AS On_time,
	CASE 
        WHEN DATENAME(WEEKDAY, [Planowana data dostawy]) = 'Friday' THEN 
            CASE 
                WHEN [data przyjecia] <= DATEADD(DAY, 3, [Planowana data dostawy]) and [Ilosc dostarczona] >= iloscZam THEN 1.0
                ELSE 0
            END
        ELSE 
            CASE 
                WHEN [data przyjecia] <= DATEADD(DAY, 2, [Planowana data dostawy]) and [Ilosc dostarczona] >= iloscZam THEN 1.0
                ELSE 0
            END
    END AS OTIF,
    (CASE 
        WHEN DATENAME(WEEKDAY, [Planowana data dostawy]) = 'Friday' AND 
             DATENAME(WEEKDAY, [data przyjecia]) = 'Monday' AND 
             DATEDIFF(DAY, [Planowana data dostawy], [data przyjecia]) = 3 THEN DATEDIFF(DAY, Data_zam, [Planowana data dostawy]) - 2
		WHEN [Planowana data dostawy] = '1900-01-01' then NULL
        ELSE DATEDIFF(DAY, Data_zam, [Planowana data dostawy])
    END) * 1.0 AS Days_diff
FROM analizy.dbo.ms_realizacja_zamowien
WHERE Data_zam >= '2025-01-01'
  AND StatusZam = 10
)
SELECT miesiac, Logo_dost, sum([Ilosc dostarczona])/sum(iloscZam) as SL_qnt, sum(WartoscPZ)/sum(wartoscZAM) as SL_value, sum(On_time)/sum(1) On_time, sum(OTIF)/sum(1) OTIF, avg(Days_diff) Lead_time, sum(WartoscPZ) obrot
from tb1
group by miesiac, Logo_dost
"""

df = pd.read_sql(sql_query, con=engine)

col_new = {'SL_qnt':'Quantitative order fulfillment rate'
,'SL_value':'Value order fulfillment rate'
,'Lead_time':'Lead time'
,'On_time':'On-time delivery'
,'OTIF':'On-time in fulfillment rate'
,'obrot':'Turnover in thousands'}
df = df.rename(columns=col_new)

df_long = df.melt(id_vars=['miesiac', 'Logo_dost'], var_name='variable', value_name='value')
result = df_long.pivot_table(index=['Logo_dost', 'variable'], columns='miesiac', values='value')
result = result.reindex(columns=range(1, 13))
result = result.reset_index()
result['variable'] = pd.Categorical(result['variable'], categories=col_new.values(), ordered=True)
result = result.sort_values(by=['Logo_dost', 'variable'])
result = result.rename(columns={'variable':'Metric'})

# Define formatting rules
percent_metrics = [
    "On-time delivery",
    "On-time in fulfillment rate",
    "Quantitative order fulfillment rate",
    "Value order fulfillment rate"
]
int_metrics = ["Turnover in thousands"]
float_metrics = ["Lead time"]

def format_value(val, metric):
    if val == "" or pd.isna(val):
        return ""
    val = float(val)
    if metric in percent_metrics:
        val = min(val * 100, 100)
        return f"{round(val):.0f}%"
    elif metric in int_metrics:
        return f"{int(round(val)):,}".replace(",", "'")
    elif metric in float_metrics:
        return f"{val:.1f}"
    else:
        return str(val)  # fallback

# Build the formatted result
json_result = {}
for logo, group in result.groupby("Logo_dost"):
    variables = group["Metric"].tolist()
    data = []
    for _, row in group.iterrows():
        metric = row["Metric"]
        formatted_row = [format_value(row[month], metric) for month in [i for i in range(1, 13)]]
        data.append(formatted_row)
    json_result[logo] = {
        "variable": variables,
        "data": data
    }

template = Template(html_template)
html_output = template.render(
    date=formatted_date,
    title ='Supplier dashboard',
    tableData = json_result
)

with open('supplier_dashboard.html', 'w', encoding='utf-8') as f:
    f.write(html_output)