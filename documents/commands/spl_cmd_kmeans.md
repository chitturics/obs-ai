---
 command: kmeans
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/kmeans
 title: kmeans
 download_date: 2026-02-03 09:10:08
---

 # kmeans

Partitions the events into k clusters, with each cluster defined by its mean value. Each event belongs to the cluster with the nearest mean value. Performs k-means clustering on the list of fields that you specify. If no fields are specified, performs the clustering on all numeric fields. Events in the same cluster are moved next to each other. You have the option to display the cluster number for each event.

kmeans [kmeans-options...] [field-list]

#### Required arguments

#### Optional arguments

#### kmeans options

#### Limits

The number of clusters to collect the values into -- k -- is not permitted to exceed maxkvalue. The maxkvalue is specified in the limits.conf file, in the [kmeans] stanza.  The maxkvalue default is 1000.

When a range is given for the k option, the total distance between the beginning and ending cluster counts is not permitted to exceed maxkrange. The maxkrange is specified in the limits.conf file, in the [kmeans] stanza.  The maxkrange default is 100.

The above limits are designed to avoid the computation work becoming unreasonably expensive.

The total number of values which are clustered by the algorithm (typically the number of input results) is limited by the maxdatapoints parameter in the [kmeans] stanza of limits.conf.  If this limit is exceeded at runtime, a warning message displays in Splunk Web.  This defaults to 100000000 or 100 million. This maxdatapoints limit is designed to avoid exhausting memory.

Example 1: Group search results into 4 clusters based on the values of the "date_hour" and "date_minute" fields.

Example 2: Group results into 2 clusters based on the values of all numerical fields.

anomalies, anomalousvalue, cluster, outlier,
 