#!/usr/bin/env python3
import json
import time
from datetime import datetime

# 当前时间戳
now = 1776277021
stale_sec = 7 * 86400  # 7天

# 任务数据（简化版）
tasks_data = [
    {'taskId': '52199673730', 'createdTime': 1776240539000, 'subject': '审批系统', 'finalStatusStage': 2, 'priority': 40},
    {'taskId': '52035415093', 'createdTime': 1776146566000, 'subject': '测试待办创建', 'finalStatusStage': 2, 'priority': 20},
    {'taskId': '52126370932', 'createdTime': 1776145972000, 'subject': '审批系统', 'finalStatusStage': 2, 'priority': 40},
    {'taskId': '51649833565', 'createdTime': 1774835235000, 'subject': '马迪提交的补卡申请', 'finalStatusStage': 2, 'priority': 20, 'dueTime': 1774842435463},
    {'taskId': '51566530813', 'createdTime': 1774599245000, 'subject': '马迪提交的补卡申请', 'finalStatusStage': 2, 'priority': 20, 'dueTime': 1774606445011},
    {'taskId': '51474195139', 'createdTime': 1774599215000, 'subject': '马迪提交的补卡申请', 'finalStatusStage': 2, 'priority': 20, 'dueTime': 1774606415824},
    {'taskId': '51566252330', 'createdTime': 1774340112000, 'subject': '郭兴提交的请假 Apply for Leave', 'finalStatusStage': 2, 'priority': 20, 'dueTime': 1774347312569},
    {'taskId': '51309576842', 'createdTime': 1773648670000, 'subject': '郭兴提交的请假 Apply for Leave', 'finalStatusStage': 2, 'priority': 20, 'dueTime': 1773655870080},
    {'taskId': '51100826264', 'createdTime': 1773360401000, 'subject': '郭兴提交的请假 Apply for Leave', 'finalStatusStage': 2, 'priority': 20, 'dueTime': 1773367601377},
    {'taskId': '50976555494', 'createdTime': 1773278594000, 'subject': '襄江帅提交的请假 Apply for Leave', 'finalStatusStage': 2, 'priority': 20, 'dueTime': 1773285794647},
]

print('=== 待办任务风险分析 ===\n')

risk_tasks = []
for task in tasks_data:
    created_sec = task['createdTime'] // 1000
    age = now - created_sec
    age_days = age / 86400
    
    # 检查是否超过7天
    if age > stale_sec:
        risk_info = {
            'taskId': task['taskId'],
            'subject': task['subject'],
            'age_days': round(age_days, 1),
            'priority': task['priority'],
        }
        
        # 检查是否逾期
        if 'dueTime' in task:
            due_sec = task['dueTime'] // 1000
            if now > due_sec:
                overdue_days = (now - due_sec) / 86400
                risk_info['overdue_days'] = round(overdue_days, 1)
                risk_info['status'] = 'overdue'
            else:
                risk_info['status'] = 'stale'
        else:
            risk_info['status'] = 'stale'
        
        risk_tasks.append(risk_info)
        
        print(f'任务ID: {task["taskId"]}')
        print(f'  标题: {task["subject"]}')
        print(f'  年龄: {age_days:.1f} 天')
        print(f'  优先级: {task["priority"]}')
        if 'overdue_days' in risk_info:
            print(f'  状态: 已逾期 {overdue_days:.1f} 天')
        else:
            print(f'  状态: 停滞 {age_days:.1f} 天')
        print()

print(f'总计发现 {len(risk_tasks)} 个风险任务')
