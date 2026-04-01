---
 command: gauge
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/gauge
 title: gauge
 download_date: 2026-02-03 09:08:27
---

 # gauge

Use the gauge command to transform your search results into a format that can be used with the gauge charts. Gauge charts are a visualization of a single aggregated metric, such as a count or a sum.

The output of the gauge command is a single numerical value stored in a field called x. You can specify a range to display in the gauge or use the default range of 0 to 100.

For more information about using the gauge command with the gauge chart types, see  Using gauges in the Gauges section in Dashboards and Visualizations.

#### Required arguments

#### Optional arguments

You can create gauge charts without using the gauge command as long as your search results in a single value. The advantage of using the  gauge command is that you can specify a set of range values instead of using the default range values of 0 to 100.

#### Specifying ranges

If you specify range values, you must specify at least two values.  The gauge begins at the first value and ends at the last value that you specify.

If you specify more than two range_val arguments, the intermediate range values are used to split the total range into subranges. Each subrange displays in different color, which creates a visual distinction.

The range values are returned as a series of fields called y1, y2, and so on.

If you do not specify range values, the range defaults to a low value of 0 and a high value of 100.

If a single range value is specified, it is ignored.

#### Gauge colors

With a gauge chart, a single numerical value is mapped against a set of colors. These colors can have particular business meaning or business logic. As the value changes over time, the gauge marker changes position within this range.

The color ranges in the gauge chart are based on the range values that you specify with the gauge command. When you specify range values, you define the overall numerical range represented by the gauge. You can define the size of the colored bands within that range. If you want to use the color bands, add four range values to the search string. These range values indicate the beginning and end of the range. These range values also indicate the relative sizes of the color bands within this range.

#### 1. Create a gauge with multiple ranges

Count the number of events and display the count on a gauge with four ranges, from 0-750, 750-1000, 1000-1250, and 1250-1500.

Start by generating the results table using this search. Run the search using the Last 15 minutes time range.

index=_internal | stats count as myCount | gauge myCount 750 1000 1250 1500

The results appear on the Statistics tab and look something like this:

| x | y1 | y2 | y3 | y4 |
| --- | --- | --- | --- | --- |
| 3321 | 750 | 1000 | 1250 | 1500 |

Click on the Visualizations tab. There are three types of gauges that you can choose from: radial, filler, and marker.  The following image shows the radial gauge that is created based on the search results.

For more information about using the gauge command with the gauge chart type, see the Gauges section in Dashboard and  Visualizations.
 