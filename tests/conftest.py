import os

# 测试环境关闭公网鉴权、关闭后台提醒循环（.env 里的真实配置不 override 已存在的变量）
os.environ["BANWUTONG_AUTH_USER"] = ""
os.environ["BANWUTONG_AUTH_PASSWORD"] = ""
os.environ["BANWUTONG_REMINDERS_DISABLED"] = "1"
