---
 command: transaction
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/transaction
 title: transaction
 download_date: 2026-02-03 09:19:52
---

 # transaction

The transaction command finds transactions based on events that meet various constraints. Transactions are made up of the raw text (the _raw field) of each member, the time and date fields of the earliest member, as well as the union of all other fields of each member.

Additionally, the transaction command adds two fields to the raw events, duration and eventcount. The values in the duration field show the difference between the timestamps for the first and last events in the transaction. The values in the eventcount field show the number of events in the transaction.

See About transactions in the Search Manual.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

#### Txn definition options

#### Filter string options

These options are used with the startswith and endswith arguments.

#### Memory control options

If you have Splunk Cloud, Splunk Support administers the settings in the limits.conf file on your behalf.

#### Multivalue rendering options

The transaction command is a centralized streaming command. See Command types.

In the output, the events in a transaction are grouped together as multiple values in the Events field. Each event in a transaction starts on a new line by default.

If there are more than 5 events in a transaction, the remaining events in the transaction are collapsed. A message appears at the end of the transaction which gives you the option to show all of the events in the transaction.

#### Specifying multiple fields

The Splunk software does not necessarily interpret the transaction defined by multiple fields as a conjunction (field1 AND field2 AND field3) or a disjunction (field1 OR field2 OR field3) of those fields. If there is a transitive relationship between the fields in the fields list and if the related events appear in the correct sequence, each with a different timestamp, transaction command will try to use it. For example, if you searched for

You might see the following events grouped into a transaction:

#### Descending chronological order required

The transaction command requires that the incoming events be in descending chronological order.  Some commands, such as eval, might change the order or time labeling of events.  If one of these commands precedes the transaction command, your search returns an error unless you include a sort command in your search.  The sort command must occur immediately before the transaction command to reorder the search results in descending chronological order.

#### 1. Transactions with the same host, time range, and pause

Group search results that have the same host and cookie value, occur within 30 seconds, and do not have a pause of more than 5 seconds between the events.

#### 2. Transactions with the same "from" value, time range, and pause

Group search results that have the same value of "from", with a maximum span of 30 seconds, and a pause between events no greater than 5 seconds into a transaction.

#### 3. Transactions with the same field values

You have events that include an alert_level. You want to create transactions where the level is equal. Using the streamstats command, you can remember the value of the alert level for the current and previous event. Using the transaction command, you can create a new transaction if the alert level is different. Output specific fields to table.

#### 1. Transactions of Web access events based on IP address

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range Yesterday when you run the search. |

Define a transaction based on Web access events that share the same IP address. The first and last events in the transaction should be no more than thirty seconds apart and each event should not be longer than five seconds apart.

This produces the following events list. The clientip for each event in the transaction is highlighted.

```
host
```

```
source
```

#### 2. Transaction of Web access events based on host and client IP

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range Yesterday when you run the search. |

Define a transaction based on Web access events that have a unique combination of host and clientip values. The first and last events in the transaction should be no more than thirty seconds apart and each event should not be longer than five seconds apart.

This search produces the following events list.

```
clientip
```

```
host
```

#### 3. Purchase transactions based on IP address and time range

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range Yesterday when you run the search. |

This search defines a purchase transaction as 3 events from one IP address which occur in a 10 minute span of time.

This search defines a purchase event based on Web access events that have the action=purchase value. These results are then piped into the transaction command. This search identifies purchase transactions by events that share the same clientip, where each session lasts no longer than 10 minutes, and includes no more than 3 events.

This search produces the following events list:

#### 4. Email transactions based on maxevents and endswith

| This example uses sample email data. You should be able to run this search on any email data by replacing the sourcetype=cisco:esa with the sourcetype value and the mailfrom field with email address field name in your data. For example, the email might be To, From, or Cc). |

This example defines an email transaction as a group of up to 10 events. Each event contains the same value for the mid (message ID), icid (incoming connection ID), and dcid (delivery connection ID). The last event in the transaction contains a Message done string.

This search produces the following list of events:

#### 5. Email transactions based on maxevents, maxspan, and mvlist

| This example uses sample email data. You should be able to run this search on any email data by replacing the sourcetype=cisco:esa with the sourcetype value and the mailfrom field with email address field name in your data. For example, the email might be To, From, or Cc). |

This example defines an email transaction as a group of up to 10 events. Each event contains the same value for the mid (message ID), icid (incoming connection ID), and dcid (delivery connection ID). The first and last events in the transaction should be no more than thirty seconds apart.

By default, the values of multivalue fields are suppressed in search results with the default setting for mvlist, which is false. Specifying mvlist=true in this search displays all of the values of the selected fields. This produces the following events list:

#### 6. Transactions with the same session ID and IP address

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

Define a transaction as a group of events that have the same session ID, JSESSIONID, and come from the same IP address, clientip, and where the first event contains the string, "view", and the last event contains the string, "purchase".

The search defines the first event in the transaction as events that include the string, "view", using the startswith="view" argument. The endswith="purchase" argument does the same for the last event in the transaction.

This example then pipes the transactions into the where command and the duration field to filter out all of the transactions that took less than a second to complete. The where filter cannot be applied before the transaction command because the duration field is added by the transaction command.

You might be curious about why the transactions took a long time, so viewing these events might help you to troubleshoot.

You won't see it in this data, but some transactions might take a long time because the user is updating and removing items from their shopping cart before they completes the purchase. Additionally, this search is run over all events. There is no filtering before the transaction command. Anytime you can filter the search before the first pipe, the faster the search runs.

#### 7. Sort order when using maxspan and maxpause

Pay careful attention to the sort order of your events when using the maxspan and maxpause arguments with the transaction command because searches with events sorted in ascending chronological order return incorrect results.

For example, the following search returns expected results because the search uses | sort -_time to sort events in descending chronological order before the maxspan argument is used:

The results look like this:

| _raw | _time | closed_txn | count | duration | eventcount | field_match_sum | linecount | user |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
|  | 2024-07-16 16:10:30 | 1 | 10 9 | 10 | 2 | 2 | 2 | nobody |
|  | 2024-07-16 16:10:10 | 1 | 7 8 | 10 | 2 | 2 | 2 | nobody |
|  | 2024-07-16 16:09:50 | 1 | 5 6 | 10 | 2 | 2 | 2 | nobody |
|  | 2024-07-16 16:09:30 | 1 | 3 4 | 10 | 2 | 2 | 2 | nobody |
|  | 2024-07-16 16:09:10 | 0 | 1 2 | 10 | 2 | 2 | 2 | nobody |

In contrast, the following search doesn't generate the correct results because events are sorted in ascending chronological order by default before the maxspan argument is used:

The results look like this:

| _raw | _time | closed_txn | count | duration | eventcount | field_match_sum | linecount | user |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
|  | 2024-07-16 16:09:17 | 0 | 1  10  2  3  4  5  6  7  8  9 | 90 | 10 | 10 | 10 | nobody |

Have questions? Visit Splunk Answers and see what questions and answers the Splunk community has using the transaction command.
 