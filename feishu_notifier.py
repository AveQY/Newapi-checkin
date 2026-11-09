# -*- coding: utf-8 -*-
"""
飞书通知模块
把签到结果推送到飞书群「自定义机器人」Webhook。

支持两种安全模式，按需配置：
  - 不配密钥：直接用 webhook 发送（安全设置可为「自定义关键词」或无校验）
  - 配 FEISHU_SECRET：自动追加 timestamp + sign 签名（安全设置为「签名校验」时用）

环境变量：
  FEISHU_WEBHOOK  必填，机器人 webhook 地址
  FEISHU_SECRET   可选，签名校验密钥
"""

import base64
import hashlib
import hmac
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    requests = None


def _format_quota(quota) -> str:
    """把额度数值格式化成 1.2K / 3.4M 这种短形式。"""
    try:
        q = float(quota)
    except (TypeError, ValueError):
        return str(quota)
    if q >= 1_000_000:
        return f'{q / 1_000_000:.1f}M'
    if q >= 1000:
        return f'{q / 1000:.1f}K'
    return str(int(q)) if q == int(q) else str(round(q, 2))


class FeishuNotifier:
    """飞书自定义机器人通知类"""

    def __init__(self, webhook_url: str, secret: Optional[str] = None):
        self.webhook_url = webhook_url
        self.secret = (secret or '').strip()

    def _signed_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """需要签名校验时，追加 timestamp 与 sign 字段。"""
        if not self.secret:
            return payload
        ts = str(int(time.time()))
        string_to_sign = f'{ts}\n{self.secret}'
        digest = hmac.new(
            string_to_sign.encode('utf-8'), digestmod=hashlib.sha256
        ).digest()
        signed = dict(payload)
        signed['timestamp'] = ts
        signed['sign'] = base64.b64encode(digest).decode('utf-8')
        return signed

    def _post(self, payload: Dict[str, Any]) -> bool:
        if requests is None:
            print('[飞书通知] 缺少 requests 依赖，无法发送')
            return False
        try:
            resp = requests.post(
                self.webhook_url, json=self._signed_payload(payload), timeout=20
            )
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            print(f'[飞书通知] 发送异常: {exc}')
            return False

        code = data.get('code', data.get('StatusCode'))
        if code == 0:
            return True
        print(f'[飞书通知] 发送失败: {data}')
        return False

    def send_text(self, text: str) -> bool:
        return self._post({'msg_type': 'text', 'content': {'text': text}})

    def send_post(self, title: str, lines: List[str]) -> bool:
        """富文本消息：一个标题 + 多行正文，飞书里比纯文本更好读。"""
        content = [[{'tag': 'text', 'text': str(line)}] for line in lines]
        return self._post({
            'msg_type': 'post',
            'content': {'post': {'zh_cn': {'title': title, 'content': content}}},
        })


def build_feishu_lines(results: List[Dict[str, Any]], execution_time: str) -> List[str]:
    """把签到结果整理成飞书富文本的正文行。"""
    success_list = [r for r in results if r.get('success')]
    fail_list = [r for r in results if not r.get('success')]

    lines = [f'执行时间: {execution_time}', '']

    for r in success_list:
        name = r.get('name') or '未知账号'
        detail = str(r.get('message', '成功'))
        quota = r.get('quota_awarded', 0)
        if quota:
            detail = f'{detail} (+{_format_quota(quota)})'
        lines.append(f'✅ {name}  {detail}')

    for r in fail_list:
        name = r.get('name') or '未知账号'
        lines.append(f'❌ {name}  {r.get("message", "失败")}')

    lines.append('')
    lines.append(f'成功 {len(success_list)} / 失败 {len(fail_list)}')
    return lines


def send_checkin_notification(
    results: List[Dict[str, Any]], execution_time: Optional[str] = None
) -> bool:
    """发送签到结果到飞书群机器人。"""
    webhook_url = os.environ.get('FEISHU_WEBHOOK', '').strip()
    secret = os.environ.get('FEISHU_SECRET', '').strip()

    if not webhook_url:
        print('[飞书通知] 未配置 FEISHU_WEBHOOK，跳过通知')
        return False

    if not execution_time:
        execution_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    success_count = len([r for r in results if r.get('success')])
    fail_count = len([r for r in results if not r.get('success')])

    if fail_count == 0:
        title = f'✅ 签到成功 ({success_count}个账号)'
    elif success_count == 0:
        title = f'❌ 签到失败 ({fail_count}个账号)'
    else:
        title = f'📋 签到完成 (成功{success_count}/失败{fail_count})'

    notifier = FeishuNotifier(webhook_url, secret or None)
    ok = notifier.send_post(title, build_feishu_lines(results, execution_time))
    print('[飞书通知] 发送成功' if ok else '[飞书通知] 发送失败')
    return ok
