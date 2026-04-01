---
 command: anomalies
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/anomalies
 title: anomalies
 download_date: 2026-02-03 09:01:38
---

 # anomalies

Use the anomalies command to look for events or field values that are unusual or unexpected.

The anomalies command assigns an unexpectedness score to each event and places that score in a new field named unexpectedness. Whether the event is considered anomalous or not depends on a threshold value. The threshold value is compared to the unexpectedness score. The event is considered unexpected or anomalous if the unexpectedness score is greater than the threshold  value.

After you use the anomalies command in a search, look at the Interesting Fields list in the Search & Reporting window. Select the unexpectedness field to see information about the values in your events.

The unexpectedness score of an event is calculated based on the similarity of that event (X) to a set of previous events (P).

The formula for unexpectedness is:

In this formula, s( ) is a metric of how similar or uniform the data is. This formula provides a measure of how much adding X affects the similarity of the set of events. The formula also normalizes the results for the differing event sizes.

Note: Use current Splunk machine learning (ML) tools to take advantage of the latest algorithms and get the most powerful results. See About the Splunk Machine Learning Toolkit
in the Splunk Machine Learning Toolkit.

The required syntax is in bold.

#### Optional arguments

#### 1. Specify a denylist file of the events to ignore

The following example shows the interesting events, ignoring any events in the denylist 'boringevents'.  Sort the event list in descending order, with highest value in the unexpectedness field listed first.

... | anomalies denylist=boringevents | sort -unexpectedness

#### 2. Find anomalies in transactions

This example uses transactions to find regions of time that look unusual.

#### 3. Identify anomalies by source

Look for anomalies in each source separately. A pattern in one source does not affect that it is anomalous in another source.

#### 4. Specify a threshold when identifying anomalies

This example shows how to tune a search for anomalies using the threshold value. 
Start with a search that uses the default threshold value.

index=_internal | anomalies BY group  | search group=*

This search looks at events in the _internal index and calculates an unexpectedness score for sets of events that have the same group value.

- The sliding set of events that are used to calculate the unexpectedness score for each unique group value includes only the events that have the same group value.
- The search command is used to show events that only include the group field.

The unexpectedness and group fields appear in the list of Interesting fields. Click on the field name and then click Yes to move the field to the Selected fields list. The fields are moved and also appear in the search results. Your results should look something like the following image.

The key-value pairs in the first event include group=pipeline, name=indexerpipe, processor=indexer, cpu_seconds=0.022, and so forth.

With the default threshold, which is 0.01, you can see that some of these events might be very similar. The next search increases the threshold a little:

index=_internal | anomalies threshold=0.03 by group | search group=*

With the higher threshold value, the timestamps and key-value pairs show more distinction between each of the events.

Also, you might not want to hide the events that are not anomalous. Instead, you can add another field to your events that tells you whether or not the event is interesting to you. One way to do this is with the eval command:

index=_internal | anomalies threshold=0.03 labelonly=true by group | search group=* | eval threshold=0.03 | eval score=if(unexpectedness>=threshold, "anomalous", "boring")

This search uses labelonly=true so that the boring events are still retained in the results list. The eval command is used to define a field named threshold and set it to the threshold value. This has to be done explicitly because the threshold attribute of the anomalies command is not a field.

The second eval command is used to define another new field, score, that is either "anomalous" or "boring" based on how the unexpectedness compares to the threshold value. The following image shows a snapshot of the results.

anomalousvalue, cluster, kmeans, outlier
 