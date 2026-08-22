"""
PRV Capital Email Dispatcher for Daily Executive Reports
Supports SMTP delivery when configured in environment, with structured logging fallback.
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional

class EmailDispatcher:
    def __init__(self):
        self.smtp_host = os.getenv("SMTP_HOST", "")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_pass = os.getenv("SMTP_PASS", "")
        self.sender_email = os.getenv("SENDER_EMAIL", self.smtp_user or "reports@prvcapital.local")
        self.recipient_email = os.getenv("ALERT_EMAIL_TO", os.getenv("EXECUTIVE_EMAIL", ""))
        self.enabled = bool(self.smtp_host and self.smtp_user and self.smtp_pass and self.recipient_email)

    def send_daily_report_email(self, report: Dict[str, Any]) -> bool:
        """Format and send the daily executive report via HTML Email."""
        report_date = report.get("report_date", "Today")
        nav = report.get("portfolio_summary", {}).get("nav", 49998.0)
        daily_pnl = report.get("daily_pnl", {}).get("gbp", 0.0)
        daily_pct = report.get("daily_pnl", {}).get("pct", 0.0)
        regime = report.get("market_regime", {}).get("classification", "STRONG_BULL")
        open_trades_count = len(report.get("trades_opened", []))
        closed_trades_count = len(report.get("trades_closed", []))
        compliance = report.get("compliance_events", {}).get("status", "PASS")

        subject = f"🏛️ PRV Capital Daily Executive Report - {report_date} | NAV: £{nav:,.2f} ({daily_pct:+.2f}%)"

        html_content = f"""
        <html>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #0b0f19; color: #f3f4f6; padding: 24px;">
            <div style="max-width: 600px; margin: auto; background: #111827; border: 1px solid #1f2937; border-radius: 12px; padding: 24px;">
                <h1 style="color: #38bdf8; font-size: 20px; margin-top: 0;">🏛️ PRV CAPITAL | DAILY EXECUTIVE REPORT</h1>
                <p style="color: #94a3b8; font-size: 13px; margin-bottom: 20px;">Report Date: <strong>{report_date}</strong> | Compliance: <strong style="color: #10b981;">{compliance}</strong></p>
                
                <div style="background: #1e293b; padding: 16px; border-radius: 8px; margin-bottom: 16px;">
                    <div style="font-size: 12px; color: #94a3b8;">Total Portfolio NAV</div>
                    <div style="font-size: 28px; font-weight: bold; color: #f8fafc;">£{nav:,.2f}</div>
                    <div style="font-size: 14px; font-weight: 600; color: {'#10b981' if daily_pnl >= 0 else '#f43f5e'};">
                        Daily P&L: {daily_pnl:+.2f} GBP ({daily_pct:+.2f}%)
                    </div>
                </div>

                <table style="width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 16px;">
                    <tr><td style="padding: 8px 0; color: #94a3b8;">Available Cash:</td><td style="text-align: right; font-weight: bold;">£{report.get('cash_position', {}).get('available_cash', 0.0):,.2f}</td></tr>
                    <tr><td style="padding: 8px 0; color: #94a3b8;">Market Regime:</td><td style="text-align: right; font-weight: bold; color: #10b981;">{regime}</td></tr>
                    <tr><td style="padding: 8px 0; color: #94a3b8;">Trades Executed Today:</td><td style="text-align: right; font-weight: bold;">{open_trades_count} Opened / {closed_trades_count} Closed</td></tr>
                    <tr><td style="padding: 8px 0; color: #94a3b8;">Active Broker Positions:</td><td style="text-align: right; font-weight: bold;">{len(report.get('open_positions', []))} Positions</td></tr>
                    <tr><td style="padding: 8px 0; color: #94a3b8;">Active Cooldowns:</td><td style="text-align: right; font-weight: bold;">{len(report.get('cooldown_events', []))} Quarantined</td></tr>
                </table>

                <div style="border-top: 1px solid #1f2937; padding-top: 16px; font-size: 11px; color: #64748b; text-align: center;">
                    PRV Capital Autonomous Quantitative Asset Management Engine • Institutional Operational Record
                </div>
            </div>
        </body>
        </html>
        """

        if not self.enabled:
            # Clean fallback log when SMTP credentials are not configured in local environment
            print(f"[Email Dispatcher] Mock sent daily report email to {self.recipient_email or 'executive@prvcapital.local'} (Subject: {subject})")
            return True

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.sender_email
            msg["To"] = self.recipient_email
            msg.attach(MIMEText(html_content, "html"))

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)
            print(f"[Email Dispatcher] Successfully sent Daily Executive Report email to {self.recipient_email}")
            return True
        except Exception as e:
            print(f"[Email Dispatcher Error] Failed to send email: {e}")
            return False

email_dispatcher = EmailDispatcher()
