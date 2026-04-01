---
 command: accum
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/accum
 title: accum
 download_date: 2026-02-03 09:01:04
---

 # accum

For each event where field is a number, the accum command calculates a running total or sum of the numbers. The accumulated sum can be returned to either the same field, or a newfield that you specify.

accum <field> [AS <newfield>]

#### Required arguments

#### Optional arguments

#### 1. Create a running total of a field

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

The following search looks for events from web access log files that were successful views of strategy games. A count of the events by each product ID is returned.

sourcetype=access_* status=200 categoryId=STRATEGY | chart count AS views by productId

The results appear on the Statistics tab and look something like this:

| productId | views |
| --- | --- |
| DB-SG-G01 | 1796 |
| DC-SG-G02 | 1642 |
| FS-SG-G03 | 1482 |
| PZ-SG-G05 | 1300 |

You can use the accum command to generate a running total of the views and display the running total in a new field called "TotalViews".

sourcetype=access_* status=200 categoryId=STRATEGY | chart count AS views by productId | accum views as TotalViews

The results appear on the Statistics tab and look something like this:

| productId | views | TotalViews |
| --- | --- | --- |
| DB-SG-G01 | 1796 | 1796 |
| DC-SG-G02 | 1642 | 3438 |
| FS-SG-G03 | 1482 | 4920 |
| PZ-SG-G05 | 1300 | 6220 |

autoregress, delta, streamstats, trendline
 