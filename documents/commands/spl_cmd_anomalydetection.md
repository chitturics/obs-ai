---
 command: anomalydetection
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/anomalydetection
 title: anomalydetection
 download_date: 2026-02-03 09:01:48
---

 # anomalydetection

A transforming command that identifies anomalous events by computing a probability for each event and then detecting unusually small probabilities. The probability is defined as the product of the frequencies of each individual field value in the event.

- For categorical fields, the frequency of a value X is the number of times X occurs divided by the total number of events.
- For numerical fields, we first build a histogram for all the values, then compute the frequency of a value X as the size of the bin that contains X divided by the number of events.

The anomalydetection command includes the capabilities of the existing anomalousvalue and outlier commands and offers a histogram-based approach for detecting anomalies.

Note: Use current Splunk machine learning (ML) tools to take advantage of the latest algorithms and get the most powerful results. See About the Splunk Machine Learning Toolkit
in the Splunk Machine Learning Toolkit.

anomalydetection [<method-option>] [<action-option>] [<pthresh-option>] [<cutoff-option>] [<field-list>]

#### Optional arguments

#### Histogram actions

When action=filter, the command returns anomalous events and filters out other events. Each returned event contains four new fields. When action=annotate, the command returns all the original events with the same four new fields added when action=filter.

| Field | Description |
| --- | --- |
| log_event_prob | The natural logarithm of the event probability. |
| probable_cause | The name of the field that best explains why the event is anomalous. No one field causes anomaly by itself, but often some field value occurs too rarely to make the event probability small. |
| probable_cause_freq | The frequency of the value in the probable_cause field. |
| max_freq | Maximum frequency for all field values in the event. |

When action=summary, the command returns a single event containing six fields.

| Output field | Description |
| --- | --- |
| num_anomalies | The number of anomalous events. |
| thresh | The event probability threshold that separates anomalous events. |
| max_logprob | The maximum of all log(event_prob). |
| min_logprob | The minimum of all log(event_prob). |
| 1st_quartile | The first quartile of all log(event_prob). |
| 3rd_quartile | The third quartile of all log(event_prob). |

#### Zscore actions

When action=filter, the command returns events with anomalous values while other events are dropped.  The kept events are annotated, like the annotate action.

When action=annotate, the command adds new fields, Anomaly_Score_Cat(field) and Anomaly_Score_Num(field), to the events that contain anomalous values.

When action=summary, the command returns a table that summarizes the anomaly statistics for each field is generated. The table includes how many events contained this field, the fraction of events that were anomalous, what type of test (categorical or numerical) were performed, and so on.

#### IQR actions

The anomalydetection command is a streaming command command. See Command types.

#### The zscore method

When you specify method=zscore, the anomalydetection command performs like the anomalousvalue command. You can specify the syntax components of the anomalousvalue command when you use the anomalydetection command with method=zscore. See the anomalousvalue command.

#### The iqr method

When you specify method=iqr, the anomalydetection command performs like the outlier command. You can specify the syntax components of the outlier command when you specify method=iqr with the anomalydetection command.
For example, you can specify the outlier options  <action>, <mark>, <param>, and <uselower>. See the outlier command.

#### Example 1: Return only anomalous events

These two searches return the same results. The arguments specified in the second search are the default values.

... | anomalydetection method=histogram action=filter

#### Example 2: Return a short summary of how many anomalous events are there

Return a short summary of how many anomalous events are there and some other statistics such as the threshold value used to detect them.

#### Example 3: Return events with anomalous values

This example specifies method=zscore to return anomalous values. The search uses the filter action to filter out events that do not have anomalous values. Events must meet the probability threshold  pthresh before being considered an anomalous value.

... | anomalydetection method=zscore action=filter pthresh=0.05

#### Example 4: Return outliers

This example uses the outlier options from the outlier command. The abbreviation tf is used for the transform action in this example.

... | anomalydetection method=iqr action=tf param=4 uselower=true mark=true

analyzefields, 
anomalies, 
anomalousvalue, 
cluster, kmeans, outlier
 