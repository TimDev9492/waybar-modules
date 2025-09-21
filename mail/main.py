#!/usr/bin/env python3

from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
import json
import os
import imaplib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import socket
import sys
import subprocess

@dataclass
class OutputInfo:
    text: str
    tooltip: str
    alt: Optional[str] = None
    percentage: Optional[int] = None

def check_mail_account(mail_config: Dict[str, Any]) -> int:
    """
    Check unread messages for a single mail account.
    
    Args:
        mail_config: Dictionary containing mail account configuration
        
    Returns:
        Number of unread messages for this account
    """
    imap_server = mail_config['imap_server']
    imap_port = mail_config['imap_port']
    user = mail_config['user']
    password = mail_config['password']
    folders = mail_config['folders']
    alias = mail_config.get('alias', user)
    
    account_unread = 0
    mail_server = None
    
    try:
        # Establish IMAP connection
        try:
            mail_server = imaplib.IMAP4_SSL(imap_server, imap_port)
        except socket.gaierror:
            # DNS resolution failed - server name doesn't exist
            return 0
        except socket.timeout:
            # Connection timed out
            return 0
        except ConnectionRefusedError:
            # Server refused connection (wrong port, server down, etc.)
            return 0
        except Exception as conn_err:
            # Other connection-related errors
            return 0
        
        # Authenticate with the server
        try:
            mail_server.login(user, password)
        except imaplib.IMAP4.error as auth_err:
            # Authentication failed - wrong credentials
            return 0
        except Exception as auth_err:
            # Other authentication errors
            return 0
        
        # Check each folder for unread messages
        for folder in folders:
            try:
                # Select the folder
                status, response = mail_server.select(folder)
                if status != "OK":
                    # Folder doesn't exist or cannot be selected
                    continue
                
                # Search for unread messages
                status, response = mail_server.search(None, 'UNSEEN')
                if status != "OK":
                    # Search command failed
                    continue
                
                # Count unread messages in this folder
                if response[0]:
                    folder_unread = len(response[0].split())
                    account_unread += folder_unread
                    
            except imaplib.IMAP4.error as folder_err:
                # IMAP protocol error when working with folder
                continue
            except Exception as folder_err:
                # Other errors when processing folder
                continue
                
    except Exception as general_err:
        # Catch-all for any other unexpected errors
        account_unread = 0
        
    finally:
        # Always try to logout and close connection
        if mail_server:
            try:
                mail_server.logout()
            except Exception:
                # Ignore logout errors - connection might already be closed
                pass
    
    return account_unread

def main() -> OutputInfo:
    # Load mail configuration
    mailmeta_path = os.path.join(os.path.dirname(__file__), '.env.mailmeta.json')
    
    try:
        with open(mailmeta_path, "r", encoding="utf-8") as file:
            mailmeta = json.load(file)
    except FileNotFoundError:
        # Configuration file doesn't exist
        return OutputInfo(
            text="Error",
            tooltip="Configuration file not found:\n<tt>{mailmeta_path}</tt>",
            alt="error"
        )
    except json.JSONDecodeError as json_err:
        # Invalid JSON in configuration file
        return OutputInfo(
            text="Error",
            tooltip="Invalid configuration file:\n<tt>{json_err}</tt>",
            alt="error"
        )
    except Exception as config_err:
        # Other errors reading configuration
        return OutputInfo(
            text="Error",
            tooltip="Configuration error:\n<tt>{config_err}</tt>",
            alt="error"
        )
    
    if not mailmeta:
        # Empty configuration
        return OutputInfo(
            text="N/A",
            tooltip="No mail accounts configured",
            alt="caught_up"
        )
    
    total_unread_messages = 0
    
    # Use ThreadPoolExecutor for concurrent processing
    # Limit concurrent connections to avoid overwhelming servers
    max_workers = min(len(mailmeta), 5)  # Max 5 concurrent connections
    
    notify = "--send-notification" in sys.argv[1:]

    if notify:
        subprocess.run([
            "notify-send",
            "--urgency=low",
            "--expire-time=3000",
            "--icon=emblem-insync-syncing",
            "--category=email",
            "Fetching emails...",
            "\n".join([f"  {mail_config.get('alias', 'Unknown')}" for mail_config in mailmeta])
        ])
    
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all mail checking tasks
            future_to_account = {
                executor.submit(check_mail_account, mail_config): mail_config.get('alias', mail_config.get('user', 'unknown'))
                for mail_config in mailmeta
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_account):
                account_alias = future_to_account[future]
                try:
                    account_unread = future.result()
                    total_unread_messages += account_unread
                except Exception as thread_err:
                    # Thread execution error
                    continue
                    
    except Exception as executor_err:
        # ThreadPoolExecutor error
        return OutputInfo(
            text="Error",
            tooltip="Threading error occurred",
            alt="error"
        )
    
    if notify:
        subprocess.run([
            "notify-send",
            "--urgency=low",
            "--expire-time=3000",
            "--icon=emblem-insync-synced",
            "--category=email",
            "Fetching complete!",
            f"You have {total_unread_messages} unread messages"
        ])

    return OutputInfo(
        text=f"{total_unread_messages}",
        alt=("unread_mails" if total_unread_messages > 0 else "caught_up"),
        tooltip=f"You have <b>{total_unread_messages}</b> unread messages"
    )

if __name__ == "__main__":
    print(json.dumps({k: v for k, v in asdict(main()).items() if v is not None}, separators=(",", ":")))