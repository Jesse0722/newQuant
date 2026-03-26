import tushare as ts
#tushare版本 1.4.24
token = "03c062d104650b5c32f4048a99c9a7ab63bcc01beb0d39613f6b6b8bdf00"

pro = ts.pro_api(token)

pro._DataApi__token = token # 保证有这个代码，不然不可以获取
pro._DataApi__http_url = 'http://139.196.25.182'  # 保证有这个代码，不然不可以获取

# #  正常使用（与官方API完全一致）
df = pro.daily(ts_code='000001.SZ', start_date='20240101', end_date='20240131')


print(df)