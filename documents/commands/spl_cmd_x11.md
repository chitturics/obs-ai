---
 command: x11
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/x11
 title: x11
 download_date: 2026-02-03 09:21:08
---

 # x11

The x11 command removes the seasonal pattern in your time-based data series so that you can  see the real trend in your data. This command has a similar purpose to the trendline command, but it uses the more sophisticated and industry popular X11 method.

The seasonal component of your time series data can be either additive or multiplicative, defined as the two types of seasonality that you can calculate with x11: add() for additive and mult() for multiplicative. See  About time-series forecasting in the Search Manual.

x11 [<type>] [<period>] (<fieldname>) [AS <newfield>]

#### Required arguments

#### Optional arguments

Example 1: In this example, the type is the default mult and the period is 15. The field name specified is count.

Note: Because span=1d, every data point accounts for 1 day. As a result, the period in this example is 15 days. 
You can change the syntax in this example to ...  | x11 15(count) because the mult type is the default type.

Example 2:  In this example, the type is add and the period is 20. The field name specified is count.

predict, trendline
 