import os, datetime
files = ["~/agent_memory/long_term.json", "~/agent_memory/schedules.json"]
report = f"# 每日报告 {datetime.date.today()}\n\n"
for fp in files:
    path = os.path.expanduser(fp)
    if os.path.exists(path):
        size = os.path.getsize(path)
        report += f"- {fp}: {size} 字节\n"
    else:
        report += f"- {fp}: 不存在\n"
print(report)
