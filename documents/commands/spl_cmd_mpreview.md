---
 command: mpreview
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/mpreview
 title: mpreview, msearch
 download_date: 2026-02-03 09:11:51
---

 # mpreview

Use mpreview to get an idea of the kinds of metric time series that are stored in your metrics indexes and to troubleshoot your metrics data.

mpreview returns a preview of the raw metric data points in a specified metric index that match a provided filter. By default, mpreview retrieves a target of five metric data points per metric time series from each metrics time-series index file (.tsidx file) associated with the search. You can change this target amount with the target_per_timeseries argument.

By design, mpreview returns metric data points in JSON format.

Note: The mpreview command cannot search data that was indexed prior to your upgrade to the 8.0.x version of the Splunk platform.

You can use the mpreview command only if your role has the run_msearch capability. See Define roles on the Splunk platform with capabilities in Securing Splunk Enterprise.

Note: Certain restricted search commands, including mpreview, mstats, tstats, typeahead, and walklex, might stop working if your organization uses field filters to protect sensitive data. See Plan for field filters in your organization in Securing the Splunk Platform.

The required syntax is in bold.

#### Required arguments

None. By default all types of terms are returned.

#### Optional arguments

This search command generates a list of individual metric data points from a specified metric index that match a provided filter. The filter can be any arbitrary boolean expression over the dimensions or the metric_name.  Specify earliest and latest to override the time range picker settings.

For more information about setting earliest and latest, see Time modifiers.

The mpreview command is designed to display individual metric data points in JSON format. If you want to aggregate metric data points, use the mstats command.

Note: All metrics search commands are case sensitive. This means, for example, that mpreview treats as the following as three distinct values of metric_name: cap.gear, CAP.GEAR, and Cap.Gear.

#### How the target_per_timeseries argument works

Unfiltered mpreview searches can cover extremely large numbers of raw metric data points. In some cases the sheer number of data points covered by the search can cause such searches to be slow or unresponsive.

The target_per_timeseries argument makes the mpreview command more responsive while giving you a relatively broad preview of your metric data. It limits the number of metric data points that mpreview can return from each metric time series in each .tsidx file covered by the search.

For example, if you have 10 metrics tsidx files that each contain 100 metric time series, and each time series has >=5 data points. If you set target_per_timeseries=5 in the search, you should expect a maximum of 10 x 100 x 5 = 5000 metric data points to be returned by the search.

On the other hand, say you have 10 metrics tsidx files that each contain 100 metric time series, but in this case, 50 of those time series have 3 data points and the other 50 of those time series have >=5 data points. If you set target_per_timeseries=5 in the search, you should expect to get 10 x ((50 x 3) + (50 x 5)) = 4000 data points.

Note: The target_per_timeseries argument is especially useful when the number of metric data points covered by your mpreview search is significantly larger than the number of metric time series covered by the search. It's not particularly helpful if the number of data points in your search are slightly larger than or equal to the number of metric time series in the search.

You can run this search to determine the number of metric data points that could potentially be covered by an mpreview search:

| metadata index=<metric_index_name> type=hosts datatype=metric | fields totalCount

You can run this search to determine the number of metric time series that could potentially be covered by an mpreview search:

| mstats count(*) WHERE index=<metric_index_name>  by _timeseries | stats count

#### Use chunk_size to regulate mpreview performance

If you find that mpreview is slow or unresponsive despite the target_per_timeseries argument you can also use chunk_size to regulate mpreview behavior. Reduce the chunk_size to make the search more responsive with the potential tradeoff of making the search slower to complete. Raise the chunk_size to help the mpreview search to complete faster, with the potential tradeoff of making it less responsive.

#### 1. Return data points that match a specific filter

This search returns individual data points from the _metrics index that match a specific filter.

| mpreview index=_metrics filter="group=queue name=indexqueue metric_name=*.current_size"

Here is an example of a JSON-formatted result of the above search.

#### 2. Return individual data points from the metrics index

#### 3. Lower chunk_size to improve mpreview performance

The following search lowers chunk_size so that it returns 100 metric time series worth of metric data points in batches from tsidx files that belong to the _metrics index. Ordinarily it would return 1000 metric time series in batches.

#### 4. Speed up an mpreview search with target_per_timeseries

The following search uses target_per_timeseries to return a maximum of five metric data points per time series in each tsidx file searched in the _metrics index.
 