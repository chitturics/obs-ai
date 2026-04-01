---
 command: searchtxn
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/searchtxn
 title: searchtxn
 download_date: 2026-02-03 09:16:29
---

 # searchtxn

Efficiently returns transaction events that match a transaction type and contain specific text.

Note: For Splunk Cloud Platform, you must create a private app that contains your transaction type definitions. If you are a Splunk Cloud administrator with experience creating private apps, see Manage private apps in your Splunk Cloud Platform deployment in the Splunk Cloud Admin Manual. If you have not created private apps, contact your Splunk account representative for help with this customization.

| searchtxn <transaction-name> [max_terms=<int>] [use_disjunct=<bool>] [eventsonly=<bool>] <search-string>

#### Required arguments

#### Optional arguments

The searchtxn command is an event-generating command. See Command types.

Generating commands use a leading pipe character and should be the first command in a search.

#### Transactions

The command works only for transactions bound together by particular field values, not by ordering or time constraints.

Suppose you have a <transactiontype>  stanza in the transactiontypes.conf.in file called  "email".  The stanza contains the following settings.

- fields=qid, pid
- search=sourcetype=sendmail_syslog to=root

The searchtxn command finds all of the events that match sourcetype="sendmail_syslog" to=root.

From those results, all fields that contain a qid or pid located are used to further search for relevant transaction events. When no additional qid or pid values are found, the resulting search is run:

sourcetype="sendmail_syslog" ((qid=val1 pid=val1) OR (qid=valn pid=valm) | transaction name=email | search to=root

#### Example 1:

Find all email transactions to root from David Smith.

transaction
 