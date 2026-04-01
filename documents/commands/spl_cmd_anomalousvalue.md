---
 command: anomalousvalue
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/anomalousvalue
 title: anomalousvalue
 download_date: 2026-02-03 09:01:43
---

 # anomalousvalue

The anomalousvalue command computes an anomaly score for each field of each event, relative to the values of this field across other events. For numerical fields, it identifies or summarizes the values in the data that are anomalous either by frequency of occurrence or number of standard deviations from the mean.

For fields that are determined to be anomalous, a new field is added with the following scheme.  If the field is numeric, such as size,  the new field will be  Anomaly_Score_Num(size). If the field is non-numeric, such as name, the new field will be Anomaly_Score_Cat(name).

Note: Use current Splunk machine learning (ML) tools to take advantage of the latest algorithms and get the most powerful results. See About the Splunk Machine Learning Toolkit
in the Splunk Machine Learning Toolkit.

anomalousvalue <av-options>... [action] [pthresh] [field-list]

#### Required arguments

#### Optional arguments

By default, a maximum of 50,000 results are returned.  This maximum is controlled by the maxresultrows setting in the [anomalousvalue] stanza in the limits.conf  file. Increasing this limit can result in more memory usage.

Note: Only users with file system access, such as system administrators, can edit the configuration files. 
Never change or copy the configuration files in the default directory. The files in the default directory must remain intact and in their original location. Make the changes in the local directory.

See How to edit a configuration file.

#### 1. Return only uncommon values from the search results

This is the same as running the following search:

#### 2. Return uncommon values from the host "reports"

host="reports" | anomalousvalue action=filter pthresh=0.02

#### 1. Return a summary of the anomaly statistics for each numeric field

| This search uses recent earthquake data downloaded from the USGS Earthquakes website. The data is a comma separated ASCII text file that contains magnitude (mag), coordinates (latitude, longitude), region (place), etc., for each earthquake recorded.
You can download a current CSV file from the USGS Earthquake Feeds and upload the file to your Splunk instance.  This example uses the All Earthquakes data from  the past 30 days. |

Search for anomalous values in the earthquake data.

source="all_month.csv"| anomalousvalue action=summary pthresh=0.02 | search isNum=YES

The numeric results are returned with multiple decimals. Use the field formatting icon, which looks like a pencil, to enable number formatting and specify the decimal precision to display.

analyzefields, anomalies, cluster, kmeans, outlier
 