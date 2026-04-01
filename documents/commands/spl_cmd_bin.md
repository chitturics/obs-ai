---
 command: bin
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/bin
 title: bin
 download_date: 2026-02-03 09:02:35
---

 # bin

Puts continuous numerical values into discrete sets, or bins, by adjusting the value of <field> so that all of the items in a particular set have the same value.

Note: The bin command is automatically called by the chart and the timechart commands. Use the bin command for only statistical operations that the chart and the timechart commands cannot process. Do not use the bin command if you plan to export all events to CSV or JSON file formats.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

#### Bin options

#### Span options

The bucket command is an alias for the bin command.

The bin command is usually a dataset processing command. If the span argument is specified with the command, the bin command is a  streaming command. See Command types.

#### Subsecond bin time spans

Subsecond span timescales, which are time spans that are made up of deciseconds (ds), centiseconds (cs), milliseconds (ms), or microseconds (us), should be numbers that divide evenly into a second. For example, 1s = 1000ms. This means that valid millisecond span values are 1, 2, 4, 5, 8, 10, 20, 25, 40, 50, 100, 125, 200, 250, or 500ms. In addition, span = 1000ms is not allowed. Use span = 1s instead.

#### 1. Specify a time span

Return the average "thruput" of each "host" for each 5 minute time span.

... | bin _time span=5m | stats avg(thruput) by _time host

#### 2. Specify the number of bins

Bin search results into 10 bins, and return the count of raw events for each bin.

#### 3. Specify an end value

Create bins with an end value larger than you need to ensure that all possible values are included.

#### 4. Specify a relative time to align the bins to

Align the time bins to 3am (local time).  Set the span to 12h. The bins will represent 3am - 3pm, then 3pm - 3am (the next day), and so on.

#### 5. Specify a UTC time to align the bins to

Align the bins to the specific UTC time of 1500567890.

chart, timechart
 