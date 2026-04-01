---
 command: sendemail
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/sendemail
 title: sendemail
 download_date: 2026-02-03 09:16:45
---

 # sendemail

Use the sendemail command to generate email notifications.  You can email search results to specified email addresses.

You must have a Simple Mail Transfer Protocol (SMTP) server available to send email. An SMTP server is not included with the Splunk instance.

CAUTION: This command is considered risky because, if used incorrectly, it can pose a security risk or potentially lose data when it runs. As a result, this command triggers SPL safeguards. See SPL safeguards for risky commands in Securing the Splunk Platform.

The required syntax is in bold:

#### Required arguments

Note: The set of domains to which you can send emails can be restricted by the Allowed Domains setting on the Email Settings page. For example, that setting could restrict you to sending emails only to addresses in your organization's email domain.

For more information, see Email notification action in the Alerting Manual.

#### Optional arguments

If you set sendresults=true and inline=false and do not specify format, a CSV file is attached to the email.

Note: If you use fields as tokens in your sendemail messages, use the rename command to remove curly brace characters such as { and } from them before they are processed by the sendemail command. The sendemail command cannot interpret curly brace characters when they appear in tokens such as $results$.

#### Capability requirements

To use sendemail, your role must have the schedule_search and list_settings capabilities.

#### 1: Send search results to the specified email

Send search results to the specified email. By default, the results are formatted as a table.

#### 2: Send search results in raw format

Send search results in a raw format with the subject "myresults".

#### 3. Include a PDF attachment, a message, and raw inline results

Send an email notification with a PDF attachment, a message, and raw inline results.

#### 4: Use email notification tokens with the sendemail command

You can use the eval command in conjunction with email notification tokens to customize your search results emails. The search in the following example sends an email to sample@splunk.com with a custom message that says sample sendemail message body.

See Use tokens in email notifications in the Splunk Cloud Platform Alerting Manual.
 