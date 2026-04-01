---
 command: cluster
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/cluster
 title: cluster
 download_date: 2026-02-03 09:03:11
---

 # cluster

The cluster command groups events together based on how similar they are to each other. Unless you specify a different field, cluster groups events based on the contents of the _raw field. The default grouping method is to break down the events into terms (match=termlist) and compute the vector between events. Set a higher threshold value for t, if you want the command to be more discriminating about which events are grouped together.

The result of the cluster command appends two new fields to each event. You can specify what to name these fields with the countfield and labelfield parameters, which default to cluster_count and cluster_label. The cluster_count value is the number of events that are part of the cluster, or the cluster size. Each event in  the cluster is assigned the cluster_label value of the cluster it belongs to. For example, if the search returns 10 clusters, then the clusters are labeled from 1 to 10.

cluster [slc-options]...

#### Optional arguments

#### SLC options

The cluster command is a streaming command or a dataset processing command, depending on which arguments are specified with the command. See Command types.

Use the cluster command to find common or rare events in your data. For example, if you are investigating an IT problem, use the cluster command to find anomalies. In this case, anomalous events are those that are not grouped into big clusters or clusters that contain few events. Or, if you are searching for errors, use the cluster command to see approximately how many different types of errors there are and what types of errors are common in your data.

#### Example 1

Quickly return a glimpse of anything that is going wrong in your Splunk deployment.
Your role must have the appropriate capabilities to access the internal indexes.

index=_internal source=*splunkd.log* log_level!=info | cluster showcount=t | table cluster_count _raw | sort -cluster_count

This search takes advantage of what Splunk software logs about its operation in the _internal index. It returns all logs where the log_level is DEBUG, WARN, ERROR, FATAL and clusters them together. Then it sorts the clusters by the count of events in each cluster.

The results appear on the Statistics tab and look something like this:

| cluster_count | raw |
| --- | --- |
| 303010 | 03-20-2018 09:37:33.806 -0700 ERROR HotDBManager - Unable to create directory /Applications/Splunk/var/lib/splunk/_internaldb/db/hot_v1_49427345 because No such file or directory |
| 151506 | 03-20-2018 09:37:33.811 -0700 ERROR pipeline - Uncaught exception in pipeline execution (indexer) - getting next event |
| 16390 | 04-05-2018 08:30:53.996 -0700 WARN SearchResultsMem - Failed to append to multival. Original value not converted successfully to multival. |
| 486 | 03-20-2018 09:37:33.811 -0700 ERROR BTreeCP - failed: failed to mkdir /Applications/Splunk/var/lib/splunk/fishbucket/splunk_private_db/snapshot.tmp: No such file or directory |
| 216 | 03-20-2018 09:37:33.814 -0700 WARN DatabaseDirectoryManager - idx=_internal Cannot open file='/Applications/Splunk/var/lib/splunk/_internaldb/db/.bucketManifest99454_1652919429_tmp' for writing bucket manifest (No such file or directory) |
| 216 | 03-20-2018 09:37:33.814 -0700 ERROR SearchResultsWriter - Unable to open output file: path=/Applications/Splunk/var/lib/splunk/_internaldb/db/.bucketManifest99454_1652919429_tmp error=No such file or directory |

#### Example 2

Search for events that don't cluster into large groups.

This returns clusters of events and uses the sort command to display them in ascending order based on the cluster size, which are the values of cluster_count. Because they don't cluster into large groups, you can consider these rare or uncommon events.

#### Example 3

Cluster similar error events together and search for the most frequent type of error.

error | cluster t=0.9 showcount=t | sort - cluster_count | head 20

This searches your index for events that include the term "error" and clusters them together if they are similar. The sort command is used to display the events in descending order based on the cluster size, cluster_count, so that largest clusters are shown first. The head command is then used to show the twenty largest clusters. Now that you've found the most common types of errors in your data, you can dig deeper to find the root causes of these errors.

#### Example 4

Use the cluster command to see an overview of your data. If you have a large volume of data, run the following search over a small time range, such as 15 minutes or 1 hour, or restrict it to a source type or index.

... | cluster labelonly=t showcount=t | sort - cluster_count, cluster_label, _time | dedup 5 cluster_label

This search helps you to learn more about your data by grouping events together based on their similarity and showing you a few of events from each cluster. It uses labelonly=t to keep each event in the cluster and append them with a cluster_label. The sort command is used to show the results in descending order by its size (cluster_count), then its cluster_label, then the indexed timestamp of the event (_time). The dedup command is then used to show the first five events in each cluster, using the cluster_label to differentiate between each cluster.

anomalies, anomalousvalue, kmeans, outlier
 