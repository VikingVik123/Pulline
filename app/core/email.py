import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from app.core.config import config


logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending emails using SMTP."""
    
    @staticmethod
    def _send_email(to_email: str, subject: str, html_content: str) -> dict:
        """Internal method to send email via SMTP."""
        try:
            if not config.MAIL_USERNAME or not config.MAIL_PASSWORD or not config.MAIL_FROM:
                return {
                    "success": False,
                    "message": "Failed to send email: SMTP credentials are not fully configured",
                }

            msg = MIMEMultipart('alternative')
            msg['From'] = config.MAIL_FROM
            msg['To'] = to_email
            msg['Subject'] = subject
            
            html_part = MIMEText(html_content, 'html')
            msg.attach(html_part)
            
            if config.MAIL_SSL:
                smtp_client = smtplib.SMTP_SSL(config.MAIL_SERVER, config.MAIL_PORT, timeout=15)
            else:
                smtp_client = smtplib.SMTP(config.MAIL_SERVER, config.MAIL_PORT, timeout=15)

            with smtp_client as server:
                if config.MAIL_TLS and not config.MAIL_SSL:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                server.login(config.MAIL_USERNAME, config.MAIL_PASSWORD)
                server.send_message(msg)
            
            return {"success": True, "message": "Email sent successfully"}
        except Exception as e:
            logger.warning(
                "Email send failed",
                extra={
                    "to_email": to_email,
                    "subject": subject,
                    "mail_server": config.MAIL_SERVER,
                    "mail_port": config.MAIL_PORT,
                },
            )
            return {"success": False, "message": f"Failed to send email: {str(e)}"}
    
    @staticmethod
    def send_welcome_email(to_email: str, username: str) -> dict:
        """Send welcome email to new user."""
        html_content = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                        .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                        .button {{ display: inline-block; padding: 12px 30px; background: #667eea; color: white; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                        .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 12px; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h1>Welcome to PayBridge!</h1>
                        </div>
                        <div class="content">
                            <h2>Hi {username}! 👋</h2>
                            <p>Thank you for signing up for PayBridge - your unified payment gateway solution.</p>
                            <p>With PayBridge, you can:</p>
                            <ul>
                                <li>Accept payments from multiple providers</li>
                                <li>Manage transactions in one place</li>
                                <li>Integrate easily with your applications</li>
                                <li>Track payments in real-time</li>
                            </ul>
                            <p>Get started by creating your first app and adding payment providers!</p>
                            <a href="{config.FRONTEND_URL or 'https://paybridge.com'}/dashboard" class="button">Go to Dashboard</a>
                        </div>
                        <div class="footer">
                            <p>© 2024 PayBridge. All rights reserved.</p>
                            <p>If you didn't create this account, please ignore this email.</p>
                        </div>
                    </div>
                </body>
                </html>
                """
        return EmailService._send_email(to_email, "Welcome to PayBridge! 🚀", html_content)

    @staticmethod
    def send_verification_email(to_email: str, username: str, verification_token: str) -> dict:
        """Send email verification link to user."""
        verification_url = f"{config.FRONTEND_URL or 'http://localhost:3000'}/verify-email?token={verification_token}"
        html_content = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                        .header {{ background: #667eea; color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                        .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                        .button {{ display: inline-block; padding: 12px 30px; background: #667eea; color: white; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                        .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 12px; }}
                        .code {{ background: #fff; padding: 15px; border-left: 4px solid #667eea; margin: 20px 0; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h1>Verify Your Email</h1>
                        </div>
                        <div class="content">
                            <h2>Hi {username}! 👋</h2>
                            <p>Thanks for signing up! Please verify your email address to activate your PayBridge account.</p>
                            <p>Click the button below to verify your email:</p>
                            <a href="{verification_url}" class="button">Verify Email Address</a>
                            <p>Or copy and paste this link into your browser:</p>
                            <div class="code">{verification_url}</div>
                            <p><strong>This link will expire in 24 hours.</strong></p>
                        </div>
                        <div class="footer">
                            <p>© 2024 PayBridge. All rights reserved.</p>
                            <p>If you didn't create this account, please ignore this email.</p>
                        </div>
                    </div>
                </body>
                </html>
                """
        return EmailService._send_email(to_email, "Verify your PayBridge email address", html_content)

    @staticmethod
    def send_password_reset_email(to_email: str, username: str, reset_token: str) -> dict:
        """Send password reset link to user."""
        reset_url = f"{config.FRONTEND_URL or 'http://localhost:3000'}/reset-password?token={reset_token}"
        html_content = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                        .header {{ background: #dc2626; color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                        .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                        .button {{ display: inline-block; padding: 12px 30px; background: #dc2626; color: white; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                        .footer {{ text-align: center; margin-top: 30px; color: #666; font-size: 12px; }}
                        .code {{ background: #fff; padding: 15px; border-left: 4px solid #dc2626; margin: 20px 0; }}
                        .warning {{ background: #fef3c7; padding: 15px; border-left: 4px solid #f59e0b; margin: 20px 0; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h1>🔒 Password Reset Request</h1>
                        </div>
                        <div class="content">
                            <h2>Hi {username}!</h2>
                            <p>We received a request to reset your PayBridge account password.</p>
                            <p>Click the button below to reset your password:</p>
                            <a href="{reset_url}" class="button">Reset Password</a>
                            <p>Or copy and paste this link into your browser:</p>
                            <div class="code">{reset_url}</div>
                            <div class="warning">
                                <strong>⚠️ Security Notice:</strong>
                                <ul>
                                    <li>This link will expire in 15 minutes</li>
                                    <li>If you didn't request this, ignore this email</li>
                                    <li>Never share this link with anyone</li>
                                </ul>
                            </div>
                        </div>
                        <div class="footer">
                            <p>© 2024 PayBridge. All rights reserved.</p>
                            <p>This is an automated security email. Please do not reply.</p>
                        </div>
                    </div>
                </body>
                </html>
                """
        return EmailService._send_email(to_email, "Reset your PayBridge password", html_content)