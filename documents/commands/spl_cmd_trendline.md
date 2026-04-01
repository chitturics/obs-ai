---
 command: trendline
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/trendline
 title: trendline
 download_date: 2026-02-03 09:20:05
---

 # trendline

Computes the moving averages of fields: simple moving average (sma), exponential moving average (ema), and weighted moving average (wma) The output is written to a new field, which you can specify.

SMA and WMA both compute a sum over the period of most recent values. WMA puts more weight on recent values rather than past values. EMA is calculated using the following formula.

where alpha = 2/(period + 1) and field(t) is the current value of a field.

trendline ( <trendtype><period>"("<field>")" [AS <newfield>] )...

#### Required arguments

#### Optional arguments

Example 1: Computes a five event simple moving average for field 'foo' and writes the result to new field called 'smoothed_foo.' Also, in the same line, computes ten event exponential moving average for field 'bar'. Because no AS clause is specified, writes the result to the field 'ema10(bar)'.

Example 2: Overlay a trendline over a chart of events by month.

accum, autoregress, delta, streamstats
 