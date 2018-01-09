
from sendgrid import SendGridAPIClient

notification_template = """
Redeemer is operating normally.

Following are some statistics from the last 24 hours of operation:

TOTAL ACCOUNTS ADJUSTED: %(total_accounts_handled)s
TOTAL REDEEMED: %(total_vests_redeemed)s VESTS
MEAN REDEMPTION PER ACCOUNT: %(mean_vests_redeemed)s VESTS
MODE OF REDEMPTION: %(mode_vests_redeemed)s VESTS

Remember that I am a robot and cannot answer your emails.

Sincerely,

Redeemer

-------------------------

Tu redimes me, si me hostes interceperint? -- Plautus.
"""

error_template = """
Redeemer FAILED to run properly.

Following is the associated backtrace:

%s

This message will repeat until the error is corrected.

Remember that I am a robot and cannot answer your emails.

Sincerely,

Redeemer

--------------------------

Nec te pugnantem tua, Cyllare, forma redemit. -- Ovid.
"""

class Notifier(object):
  def __init__(self, sendgrid_api_key=None, send_messages_to=[]):
    self.send_messages_to = send_messages_to

    self.send_emails = False
    if sendgrid_api_key is not None and send_messages_to is not None:
      self.sg = SendGridAPIClient(apikey=sendgrid_api_key)
      self.send_emails = True

  def get_request_body(self, subject, template, template_args):
    return {
        "personalizations": [
          {
            "to": [ { "email": email } for email in self.send_messages_to ],
            "subject": subject
          }
        ],
        "from": {
          "email": "redeemer@steemit.com"
        },
        "content": [
          {
            "type": "text/plain",
            "value": template % template_args
          }
        ]
      }

  def send_email(self, subject, template, template_args):
    if self.send_emails:
      self.sg.client.mail.send.post(request_body=self.get_request_body(subject, template, template_args))


  def notify_stats(self, stats):
    self.send_email("Redeemer OK", notification_template, stats)

  def notify_error(self, err):
    self.send_email("Redeemer ERROR", error_template, { "error": err })

