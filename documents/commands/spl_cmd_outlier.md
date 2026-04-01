---
 command: outlier
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/outlier
 title: outlier
 download_date: 2026-02-03 09:13:04
---

 # outlier

This command is used to remove outliers, not detect them. It removes or truncates outlying numeric values in selected fields. If no fields are specified, then the outlier command attempts to process all fields.

To identify outliers and create alerts for outliers, see finding and removing outliers in the Search Manual.

Note: Use current Splunk machine learning (ML) tools to take advantage of the latest algorithms and get the most powerful results. See About the Splunk Machine Learning Toolkit
in the Splunk Machine Learning Toolkit.

outlier <outlier-options>... [<field-list>]

#### Optional arguments

#### Outlier options

The outlier command is a dataset processing command. See Command types.

Filtering is based on the inter-quartile range (IQR), which is computed from the difference between the 25th percentile and 75th percentile values of the numeric fields. If the value of a field in an event is less than (25th percentile) - param*IQR or greater than (75th percentile) + param*IQR , that field is transformed or that event is removed based on the action parameter.

Example 1: For a timechart of webserver events, transform the outlying average CPU values.

Example 2: Remove all outlying numerical values.

anomalies, anomalousvalue, cluster, kmeans

Finding and removing outliers
 