---
 command: autoregress
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/autoregress
 title: autoregress
 download_date: 2026-02-03 09:02:29
---

 # autoregress

Prepares your events for calculating the autoregression, or the moving average, by copying one or more of the previous values  for field into each event.

The first few events will lack the augmentation of prior values, since the prior values do not exist.

autoregress <field> [AS <newfield>] [ p=<int> | p=<int>-<int> ]

#### Required arguments

#### Optional arguments

If the newfield argument is not specified, the single or multiple values are copied into fields with the names <field>_p<num>. For example, if p=2-4 and field=count, the field names are count_p2, count_p3, count_p4.

The autoregress command is a centralized streaming command. See Command types.

#### Example 1:

For each event, copy the 3rd previous value of the 'ip' field into the field 'old_ip'.

#### Example 2:

For each event, copy the 2nd, 3rd, 4th, and 5th previous values of the 'count' field.

Since the new field argument is not specified, the values are copied into the fields 'count_p2', 'count_p3', 'count_p4', and 'count_p5'.

#### Example 3:

Calculate a moving average of event size over the current event and the four prior events.  This search omits the moving_average for the initial events, where the field would be wrong, because summing null fields is considered null.

... | eval rawlen=len(_raw) | autoregress rawlen p=1-4 | eval moving_average=(rawlen + rawlen_p1 + rawlen_p2 + rawlen_p3 +rawlen_p4 ) /5

accum, delta, streamstats, trendline
 