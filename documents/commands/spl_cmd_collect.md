---
 command: collect
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/collect
 title: collect, stash
 download_date: 2026-02-03 09:03:29
---

 # collect

Adds the results of a search to a summary index that you specify. You must create the summary index before you invoke the collect command.

You do not need to know how to use collect to create and use a summary index, but it can help. For an overview of summary indexing, see Use summary indexing for increased reporting efficiency in the Knowledge Manager Manual.

CAUTION: This command is considered risky because, if used incorrectly, it can pose a security risk or potentially lose data when it runs. As a result, this command triggers SPL safeguards. See SPL safeguards for risky commands in Securing the Splunk Platform.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

#### arg-options

The events are written to a file whose name format is: random-num_events.stash, unless overwritten, in a directory that your Splunk deployment is monitoring. If the events contain a _raw field, then this field is saved. If the events do not have a _raw field, one is created by concatenating all the fields into a comma-separated list of key=value pairs.

The collect command also works with real-time searches that have a time range of All time.

#### Events without timestamps

If you apply the collect command to events that do not have timestamps, the command designates a time for all of the events using the earliest (or minimum) time of the search range. For example, if you use the collect command  over the past four hours (range: -4h to +0h), the command assigns a timestamp that is four hours prior to the time that the search was launched. The timestamp is applied to all of the events without a timestamp.

If you use the collect command with a time range of All time and the events do not have timestamps, the current system time is used for the timestamps.

For more information on summary indexing of data without timestamps, see Use summary indexing for increased reporting efficiency in the Knowledge Manager Manual.

#### Copying events to a different index

You can use the collect command to copy search results to another index.
Construct a search that returns the data you want to copy, and pipe the results to the collect command. For example:

This search writes the results into the bar index. The sourcetype is changed to stash.

You can specify a sourcetype with the collect command. However, specifying a sourcetype counts against your license, as if you indexed the data again.

#### Change how collect summarizes multivalue fields on Splunk Enterprise

By default, the collect command summarizes multivalue fields as multivalue fields. For example, when collect summarizes the multivalue field alphabet = a, b, c, it adds the following field to the summary index:

However, you might prefer the collect command to break multivalue fields into separate field-value pairs when it adds them to a _raw field in a summary index. For example, if given the multivalue field alphabet = a,b,c, you can have the collect command add the following fields to a _raw event in the summary index: alphabet = "a", alphabet = "b", alphabet = "c"

If you are using Splunk Enterprise and you prefer to have collect follow this multivalue field summarization format, set the limits.conf setting format_multivalue_collect to true.

To change the format_multivalue_collect setting in your local limits.conf file and enable collect to break multivalue fields into separate fields, follow these steps.

Prerequisites

- Open or create a local limits.conf file at $SPLUNK_HOME/etc/system/local.
- Under the [collect] stanza, set format_multivalue_collect to true.

#### The collect and tstats commands

The collect command does not segment data by major breakers and minor breakers, such as characters like spaces, square or curly brackets, parenthesis, semicolons, exclamation points, periods, and colons. As a result, if either major or minor breakers are found in value strings, Splunk software places quotation marks around field values when it adds events to the summary index. These extra quotation marks can cause problems for subsequent searches. In particular, field values that have quotation marks around them can't be used in tstats searches with the PREFIX() directive. This is because PREFIX() does not support major breakers like quotation marks.

For example, in the following search with the collect command, the field values in quotes include periods as minor breakers.

| makeresults | eval application="buttercupgames.com", version="2.0" | collect index=summary source=devtest

The search results look something like this.

| _time | application | version |
| --- | --- | --- |
| 2021-12-07 11:43:48 | buttercupgames.com | 2.0 |

So far, that looks fine, right? Not exactly. Although there aren't any extra quotation marks around the field values buttercupgames.com and 2.0 that are displayed in the search results, you will see them if you look in summary index. To see what is in the summary index, run the following search:

Now you can see version="2.0" and application="buttercupgames.com". The results look something like this:

| Time | Event |
| --- | --- |
| 12/7/21
11:43:48.000 AM | 12/07/2021 11:43:48 -0800,  info_search_time=1638906228.401,  version="2.0",  application="buttercupgames.com" 
host = PF32198D     |     source = devtest     |     sourcetype = stash |

If you want to run a tstats search with the PREFIX() directive using those field values with quotation marks that are collected in a summary index like our previous example, you will need to edit your limits.conf file. You can do this by changing the collect_ignore_minor_breakers setting in the [collect] stanza from the default to true.

- Open or create a local limits.conf file at $SPLUNK_HOME/etc/system/local.
- Under the [collect] stanza, add the line collect_ignore_minor_breakers=true.

#### 1. Put "download" events into an index named "download count"

eventtypetag="download" | collect index=downloadcount

#### 2. Collect statistics on VPN connects and disconnects

You want to collect hourly statistics on VPN connects and disconnects by country.

index=mysummary 
 | geoip REMOTE_IP 
 | eval country_source=if(REMOTE_IP_country_code="US","domestic","foreign") 
 | bin _time span=1h 
 | stats count by _time,vpn_action,country_source 
 | addinfo
 | collect index=mysummary marker="summary_type=vpn, summary_span=3600, 
   summary_method=bin, search_name=\"vpn starts and stops\""

The addinfo command ensures that the search results contain fields that specify when the search was run to populate these particular index values.

#### 3. Ingest fields using the collect command and HEC formatted output

Say you want to create a few fields in your index by running the following search:

| makeresults 
| eval source="mysource", sourcetype="mysourcetype", host="myhost", sentinel="4", _raw="this is an event with a key=value pair" 
| collect index=main output_format=hec

The results look  like this:

| _raw | _time | host | sentinel | source | sourcetype |
| --- | --- | --- | --- | --- | --- |
| this is an event with a key=value pair | 2024-01-12T19:22:55.000-08:00 | myhost | 4 | mysource | mysourcetype |

To see what the event we've just generated looks like in the index, run the following search:

The following image shows that all of the fields that were specified in the search appear as fields in the index.
 