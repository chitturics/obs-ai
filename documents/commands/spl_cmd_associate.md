---
 command: associate
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/associate
 title: associate
 download_date: 2026-02-03 09:02:24
---

 # associate

The associate command identifies correlations between fields. The command tries to find a relationship between pairs of fields by calculating a change in entropy based on their values. This entropy represents whether knowing the value of one field helps to predict the value of another field.

In Information Theory, entropy is defined as a measure of the uncertainty associated with a random variable. In this case if a field has only one unique value, the field has an entropy of zero. If the field has multiple values, the more evenly those values are distributed, the higher the entropy.

The associate command  uses Shannon entropy (log base 2). The unit is in bits.

associate [<associate-options>...] [field-list]

#### Required arguments

#### Optional arguments

#### Associate-options

#### Columns in the output table

The associate command outputs a table with columns containing the following fields.

| Field | Description |
| --- | --- |
| Reference_Key | The name of the first field in a pair of fields. |
| Reference_Value | The value in the first field in a pair of fields. |
| Target_Key | The name of the second field in a pair of fields. |
| Unconditional_Entropy | The entropy of the target key. |
| Conditional_Entropy | The entropy of the target key when the reference key is the reference value. |
| Entropy_Improvement | The difference between the unconditional entropy and the conditional entropy. |
| Description | A message that summarizes the relationship between the field values that is based on the entropy calculations. The Description is a textual representation of the result. It is written in the format: "When the 'Reference_Key' has the value 'Reference_Value', the entropy of 'Target_Key' decreases from Unconditional_Entropy to Conditional_Entropy." |
| Support | Specifies how often the reference field is the reference value, relative to the total number of events. For example, how often field A is equal to value X, in the total number of events. |

#### 1. Analyze the relationship between fields in web access log files

| This example uses the sample data from the Search Tutorial. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range Yesterday when you run the search. |

This example demonstrates one way to analyze the relationship of fields in your web access logs.

sourcetype=access_* status!=200 | fields method, status | associate improv=0.05  | table Reference_Key, Reference_Value, Target_Key, Top_Conditional_Value, Description

The first part of this search retrieves web access events that returned a status that is not 200. Web access data contains many fields. You can use the associate command to see a relationship between all pairs of fields and values in your data. To simplify this example, restrict the search to two fields: method and status.

Because the associate command adds many columns to the output, this search uses the table command to display only select columns.

The results appear on the Statistics tab and look something like this:

| Reference_Key | Reference_Value | Target_Key | Top_Conditional_Value | Description |
| --- | --- | --- | --- | --- |
| method | POST | status | 503 (17.44% -> 33.96%) | When 'method' has the value 'POST', the entropy of 'status' decreases from 2.923 to 2.729. |
| status | 400 | method | GET (76.37% -> 83.45%) | When 'status' has the value '400', the entropy of 'method' decreases from 0.789 to 0.647. |
| status | 404 | method | GET (76.37% -> 81.27%) | When 'status' has the value '404', the entropy of 'method' decreases from 0.789 to 0.696. |
| status | 406 | method | GET (76.37% -> 81.69%) | When 'status' has the value '406', the entropy of 'method' decreases from 0.789 to 0.687. |
| status | 408 | method | GET (76.37% -> 80.00%) | When 'status' has the value '408', the entropy of 'method' decreases from 0.789 to 0.722. |
| status | 500 | method | GET (76.37% -> 80.73%) | When 'status' has the value '500', the entropy of 'method' decreases from 0.789 to 0.707. |

In the results you can see that there is one method and five status values in the results.

From the first row of results, you can see that when method=POST, the status field is 503 for those events. The associate command concludes that, if method=POST, the Top_Conditional_Value	 is likely to be 503 as much as 33% of the time.

The Reference_Key and Reference_Value are being correlated to the Target_Key.

The Top_Conditional_Value field states three things:

- The most common value for the given Reference_Value.
- The frequency of the Reference_Value for that field in the dataset, sometimes referred to as FRV.
- The frequency of the most common associated value in the Target_Key for the events that have the specific Reference_Value in that Reference Key. Sometimes referred to as the FCV.

The values in the Top_Conditional_Value field are formatted as "CV (FRV% -> FCV%)", for example GET (76.37% -> 83.45%).

#### 2. Return results that have at least 3 references to each other

Return results associated with each other (that have at least 3 references to each other).

index=_internal sourcetype=splunkd | associate supcnt=3

#### 3.  Analyze events from a host

Analyze all events from host "reports" and return results associated with each other.

host="reports" | associate supcnt=50 supfreq=0.2 improv=0.5

arules,
correlate, contingency
 