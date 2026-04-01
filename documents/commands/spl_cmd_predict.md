---
 command: predict
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/predict
 title: predict
 download_date: 2026-02-03 09:13:51
---

 # predict

The predict command forecasts values for one or more sets of time-series data. The command can also fill in missing data in a time-series and provide predictions for the next several time steps.

The predict command provides confidence intervals for all of its estimates. The command adds a predicted value and an upper and lower 95th percentile range to each event in the time-series. See the Usage section in this topic.

Note: Use current Splunk machine learning (ML) tools to take advantage of the latest algorithms and get the most powerful results. See About the Splunk Machine Learning Toolkit
in the Splunk Machine Learning Toolkit.

predict <field-list> [AS <newfield>] [<predict_options>]

#### Required arguments

#### Optional arguments

#### Predict options

#### Confidence intervals

The lower and upper confidence interval parameters default to lower95 and upper95. These values specify a confidence interval where 95% of the predictions are expected fall.

It is typical for some of the predictions to fall outside the confidence interval.

- The confidence interval does not cover 100% of the predictions.
- The confidence interval is about a probabilistic expectation and results do not match the expectation exactly.

#### Command sequence requirement

The predict command must be preceded by the timechart command. The  predict command requires time series data. See the Examples section for more details.

#### How it works

The predict command models the data by stipulating that there is an unobserved entity which progresses through time in different states.

To predict a value, the command calculates the best estimate of the state by considering all of the data in the past. 
To compute estimates of the states, the command hypothesizes that the states follow specific linear equations with Gaussian noise components.

Under this hypothesis, the least-squares estimate of the states are calculated efficiently. This calculation is called the Kalman filter, or Kalman-Bucy filter. For each state estimate, a confidence interval is obtained. The estimate is not a point estimate. The estimate is a range of values that contain the observed, or predicted, values.

The measurements might capture only some aspect of the state, but not necessarily the whole state.

#### Missing values

The predict command can work with data that has missing values. The command calculates the best estimates of the missing values.

Do not remove events with missing values, Removing the events might distort the periodicity of the data. Do not specify cont=false with the  timechart command. Specifying cont=false removes events with missing values.

#### Specifying span

The unit for the span specified with the timechart command must be seconds or higher.  The predict command cannot accept subseconds as an input when it calculates the period.

#### 1. Predict future access

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

Predict future access based on the previous access numbers that are stored in Apache web access log files. Count the number of access attempts using a span of 1 day.

The results appear on the Statistics tab.  Click the Visualization tab. If necessary change the chart type to a Line Chart.

#### 2. Predict future purchases for a product

| This example uses the sample data from the Search Tutorial. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

Chart the number of purchases made daily for a specific product.

- This example searches for all purchases events, defined by the action=purchase for the arc, and pipes those results into the timechart command.
- The span=1day argument buckets the count of purchases into daily chunks.

The results appear on the Statistics tab and look something like this:

| _time | count |
| --- | --- |
| 2018-06-11 | 17 |
| 2018-06-12 | 63 |
| 2018-06-13 | 94 |
| 2018-06-14 | 82 |
| 2018-06-15 | 63 |
| 2018-06-16 | 76 |
| 2018-06-17 | 70 |
| 2018-06-18 | 72 |

Add the predict command to the search to calculate the prediction for the number of purchases of the Arcade games that might be sold in the near future.

The results appear on the Statistics tab.  Click the Visualization tab. If necessary change the chart type to a Bar Chart.

#### 3. Predict the values using the default algorithm

Predict the values of foo using the default LLP5 algorithm, an algorithm that combines the LLP and LLT algorithms.

#### 4. Predict multiple fields using the same algorithm

Predict multiple fields using the same algorithm. The default algorithm in this example.

#### 5. Specifying different upper and lower confidence intervals

When specifying confidence intervals, the upper and lower confidence interval values do not need to match. This example predicts 10 values for a field using the LL algorithm, holding back the last 20 values in the data set.

#### 6. Predict the values using the LLB algorithm

This example illustrates the LLB algorithm. The foo3 field is predicted by correlating it with the foo2 field.

#### 7. Omit the last 5 data points and predict 5 future values

In this example, the search abstains from using the last 5 data points and makes 5 future predictions. The predictions correspond to the last 5 values in the data. You can judge how accurate the predictions are by checking whether the observed values fall into the predicted confidence intervals.

#### 8. Predict multiple fields using the same algorithm and the same future_timespan and holdback

Predict multiple fields using the same algorithm and same future_timespan and holdback.

#### 9. Specify aliases for fields

Use aliases for the fields by specifying the AS keyword for each field.

#### 10. Predict multiple fields using different algorithms and options

Predict multiple fields using different algorithms and different options for each field.

#### 11. Predict multiple fields using the BiLL algorithm

Predict values for foo1 and foo2 together using the bivariate algorithm BiLL.

trendline, x11
 