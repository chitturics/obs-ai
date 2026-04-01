# Splunk Machine Learning Toolkit (MLTK) Reference

## Overview

The Splunk Machine Learning Toolkit (MLTK) extends SPL with machine learning commands for training, applying, and validating models directly within Splunk. It ships with 30+ algorithms and supports 300+ via the Python for Scientific Computing (PSC) add-on. MLTK enables anomaly detection, forecasting, clustering, classification, and regression on indexed data.

---

## SPL Commands

### fit - Train and Save Models

Train a machine learning model and save it for later use.

```spl
| fit <algorithm> <response_variable> from <feature1> <feature2> ... into <model_name>
```

**Examples:**

```spl
| fit LogisticRegression is_malicious from src_bytes dst_bytes duration into malware_classifier
| fit KMeans k=5 src_bytes dst_bytes into traffic_clusters
| fit LinearRegression response_time from cpu_usage memory_usage into perf_predictor
| fit DensityFunction count dist=norm into login_anomaly_model
```

**Key parameters:**
- `into <model_name>` - Name to save the model as (required for reuse)
- `from <fields>` - Feature fields (predictors)
- Algorithm-specific params vary (e.g., `k=5` for KMeans, `dist=norm` for DensityFunction)

### apply - Apply a Saved Model

Apply a previously trained model to new data for scoring or prediction.

```spl
| apply <model_name>
```

**Examples:**

```spl
index=network | stats sum(bytes) by src_ip | apply network_outlier_model
index=endpoint | stats count by process_name | apply rare_process_model
index=web | apply response_time_predictor
```

Output fields are automatically added (e.g., `predicted(field)`, `cluster`, `isOutlier`).

### score - Validate Model Performance

Evaluate model predictions against actual values using scoring metrics.

```spl
| score <scoring_method> <actual_field> against <predicted_field>
```

**Examples:**

```spl
| score accuracy_score is_malicious against predicted(is_malicious)
| score r2_score response_time against predicted(response_time)
| score confusion_matrix actual_label against predicted(actual_label)
| score f1_score is_threat against predicted(is_threat) average=weighted
| score silhouette_score cluster
```

### summary - View Model Details

Display information about a saved model including algorithm, features, and parameters.

```spl
| summary <model_name>
```

**Example:**

```spl
| summary malware_classifier
```

Returns: algorithm type, feature names, training time, model parameters, and coefficients (where applicable).

### sample - Random Sampling and Train/Test Splits

Create random samples or partition data for cross-validation.

```spl
| sample ratio=<0-1>
| sample count=<N>
| sample partitions=<N> seed=<int>
```

**Examples:**

```spl
| sample ratio=0.1
| sample count=1000
| sample partitions=5 seed=42
| sample ratio=0.8 seed=1234
```

**Parameters:**
- `ratio` - Fraction of events to keep (0 to 1)
- `count` - Exact number of events to sample
- `partitions` - Split data into N partitions (adds `partition_number` field)
- `seed` - Random seed for reproducibility

### listmodels - List All Saved Models

List all trained models stored in the MLTK app.

```spl
| listmodels
```

Returns: model name, algorithm, creation time, and app context.

### deletemodel - Delete a Saved Model

Remove a saved model from the MLTK model store.

```spl
| deletemodel <model_name>
```

**Example:**

```spl
| deletemodel old_anomaly_detector
```

---

## Algorithms

### Classifiers

Classifiers predict categorical target variables (labels/classes).

#### LogisticRegression

Binary or multiclass classification using logistic function. Best for linearly separable data with interpretable coefficients.

```spl
| fit LogisticRegression is_malicious from bytes duration protocol into threat_classifier
| fit LogisticRegression severity from error_count latency cpu into severity_model probabilities=true
```

Parameters: `C` (regularization, default=1.0), `fit_intercept` (default=true), `probabilities` (output class probabilities).

#### RandomForestClassifier

Ensemble of decision trees for robust classification. Handles non-linear relationships and feature interactions well.

```spl
| fit RandomForestClassifier attack_type from src_bytes dst_bytes flags into attack_classifier n_estimators=100
```

Parameters: `n_estimators` (number of trees, default=100), `max_depth`, `max_features`, `random_state`.

#### DecisionTreeClassifier

Single tree classifier. Highly interpretable but prone to overfitting.

```spl
| fit DecisionTreeClassifier is_fraud from amount merchant_category location into fraud_tree max_depth=10
```

Parameters: `max_depth`, `min_samples_split`, `min_samples_leaf`, `criterion` (gini or entropy).

#### GradientBoostingClassifier

Sequential ensemble of weak learners (trees). High accuracy, slower training.

```spl
| fit GradientBoostingClassifier is_attack from feature1 feature2 feature3 into attack_gbc n_estimators=200 learning_rate=0.1
```

Parameters: `n_estimators`, `learning_rate` (default=0.1), `max_depth` (default=3), `subsample`.

#### BernoulliNB

Naive Bayes classifier for binary/boolean features. Fast training, works well with binary feature vectors.

```spl
| fit BernoulliNB is_spam from has_attachment has_link has_urgent_subject into spam_nb
```

Parameters: `alpha` (smoothing, default=1.0), `fit_prior` (default=true).

#### GaussianNB

Naive Bayes for continuous features assuming Gaussian distribution. Fast and effective baseline.

```spl
| fit GaussianNB category from feature1 feature2 feature3 into category_nb
```

Parameters: `var_smoothing` (default=1e-9).

#### SGDClassifier

Stochastic gradient descent classifier. Efficient for large datasets and online learning.

```spl
| fit SGDClassifier label from feat1 feat2 feat3 into sgd_model loss=log_loss
```

Parameters: `loss` (hinge, log_loss, modified_huber), `alpha` (regularization), `max_iter`, `penalty` (l1, l2, elasticnet).

#### SVM

Support Vector Machine for classification. Effective in high-dimensional spaces.

```spl
| fit SVM is_anomaly from dim1 dim2 dim3 into svm_classifier kernel=rbf gamma=0.1
```

Parameters: `kernel` (linear, rbf, poly, sigmoid), `C`, `gamma`, `degree` (for poly kernel).

#### MLPClassifier

Multi-layer perceptron (neural network) classifier. Learns complex non-linear patterns.

```spl
| fit MLPClassifier threat_level from f1 f2 f3 f4 into nn_classifier hidden_layer_sizes="100,50" max_iter=500
```

Parameters: `hidden_layer_sizes`, `activation` (relu, tanh, logistic), `solver` (adam, sgd, lbfgs), `max_iter`, `learning_rate`.

#### AutoPrediction

Automatically detects data type and selects the best classification or regression algorithm.

```spl
| fit AutoPrediction target from feat1 feat2 feat3 into auto_model
```

Tries multiple algorithms and selects the best performer via cross-validation.

---

### Regressors

Regressors predict continuous numeric target variables.

#### LinearRegression

Ordinary least squares linear regression. Fast, interpretable, baseline model.

```spl
| fit LinearRegression response_time from cpu_pct mem_pct disk_io into perf_model
| fit LinearRegression total_cost from num_users storage_gb into cost_estimator
```

Parameters: `fit_intercept` (default=true), `normalize` (default=false).

#### RandomForestRegressor

Ensemble of decision trees for regression. Handles non-linearity and interactions.

```spl
| fit RandomForestRegressor latency from queue_depth connections cpu into latency_rf n_estimators=100
```

Parameters: `n_estimators`, `max_depth`, `max_features`, `min_samples_split`.

#### DecisionTreeRegressor

Single tree for regression. Interpretable, captures non-linear relationships.

```spl
| fit DecisionTreeRegressor duration from payload_size protocol into duration_tree max_depth=8
```

Parameters: `max_depth`, `min_samples_split`, `min_samples_leaf`.

#### GradientBoostingRegressor

Boosted ensemble regression. High accuracy for complex relationships.

```spl
| fit GradientBoostingRegressor error_rate from load concurrency memory into error_gbr n_estimators=200
```

Parameters: `n_estimators`, `learning_rate`, `max_depth`, `subsample`, `loss` (squared_error, absolute_error, huber).

#### Lasso

L1-regularized linear regression. Performs feature selection by driving coefficients to zero.

```spl
| fit Lasso target from feat1 feat2 feat3 feat4 into lasso_model alpha=0.5
```

Parameters: `alpha` (regularization strength), `max_iter`, `fit_intercept`.

#### Ridge

L2-regularized linear regression. Prevents overfitting by shrinking coefficients.

```spl
| fit Ridge target from feat1 feat2 feat3 into ridge_model alpha=1.0
```

Parameters: `alpha` (regularization strength), `fit_intercept`, `normalize`.

#### ElasticNet

Combined L1 + L2 regularization. Balances Lasso feature selection with Ridge stability.

```spl
| fit ElasticNet target from feat1 feat2 feat3 into elasticnet_model alpha=0.5 l1_ratio=0.5
```

Parameters: `alpha`, `l1_ratio` (0=Ridge, 1=Lasso), `max_iter`.

#### KernelRidge

Kernel ridge regression. Combines Ridge with kernel trick for non-linear regression.

```spl
| fit KernelRidge target from feat1 feat2 into kernelridge_model kernel=rbf alpha=1.0
```

Parameters: `kernel` (linear, rbf, poly), `alpha`, `gamma`, `degree`.

#### SGDRegressor

Stochastic gradient descent for regression. Efficient for large datasets.

```spl
| fit SGDRegressor target from feat1 feat2 into sgd_regressor loss=squared_error
```

Parameters: `loss` (squared_error, huber, epsilon_insensitive), `alpha`, `max_iter`, `penalty`.

---

### Clustering

Clustering algorithms group similar events without labeled targets (unsupervised).

#### KMeans

Partition data into K clusters based on distance to cluster centroids. Most common clustering algorithm.

```spl
| fit KMeans src_bytes dst_bytes duration k=5 into traffic_clusters
| fit KMeans cpu mem disk k=3 into server_profiles
```

Parameters: `k` (number of clusters, required), `random_state`, `max_iter`, `init` (k-means++, random).

Output field: `cluster` (cluster assignment 0 to k-1).

#### DBSCAN

Density-based clustering. Finds arbitrarily shaped clusters and identifies noise points. Does not require specifying number of clusters.

```spl
| fit DBSCAN lat lon eps=0.5 min_samples=10 into geo_clusters
```

Parameters: `eps` (maximum distance between neighbors), `min_samples` (minimum points for core point), `metric` (euclidean, manhattan).

Output: `cluster` (-1 for noise/outlier points).

#### Birch

Memory-efficient hierarchical clustering. Scales to large datasets with incremental learning.

```spl
| fit Birch feat1 feat2 feat3 n_clusters=8 into birch_clusters
```

Parameters: `n_clusters`, `threshold` (merge radius), `branching_factor`.

#### SpectralClustering

Graph-based clustering using eigenvalues of similarity matrix. Finds non-convex clusters.

```spl
| fit SpectralClustering feat1 feat2 n_clusters=4 into spectral_clusters
```

Parameters: `n_clusters`, `affinity` (rbf, nearest_neighbors), `gamma`, `n_neighbors`.

#### AgglomerativeClustering

Bottom-up hierarchical clustering. Merges closest clusters iteratively.

```spl
| fit AgglomerativeClustering feat1 feat2 n_clusters=6 into hier_clusters linkage=ward
```

Parameters: `n_clusters`, `linkage` (ward, complete, average, single), `affinity`.

#### MiniBatchKMeans

Mini-batch variant of KMeans. Faster for large datasets, slightly less accurate.

```spl
| fit MiniBatchKMeans feat1 feat2 feat3 k=10 into streaming_clusters batch_size=100
```

Parameters: `k`, `batch_size`, `max_iter`, `random_state`.

#### MeanShift

Non-parametric clustering that finds modes (peaks) in density. Automatically determines number of clusters.

```spl
| fit MeanShift feat1 feat2 into meanshift_clusters bandwidth=2.0
```

Parameters: `bandwidth` (kernel size; auto-estimated if omitted), `bin_seeding`.

#### OPTICS

Ordering Points To Identify Clustering Structure. Extension of DBSCAN that handles varying density.

```spl
| fit OPTICS feat1 feat2 min_samples=10 into optics_clusters
```

Parameters: `min_samples`, `max_eps`, `metric`, `cluster_method` (xi, dbscan).

---

### Anomaly Detection

Algorithms that identify outliers and unusual patterns in data.

#### DensityFunction

Fits a probability density function and flags events below a threshold as anomalies. Best for univariate or low-dimensional anomaly detection.

```spl
| fit DensityFunction count dist=norm into login_anomaly_model
| fit DensityFunction response_time dist=auto threshold=0.01 into latency_anomaly
```

Parameters: `dist` (norm, exponential, auto), `threshold` (probability cutoff), `full_output` (include probability scores).

Output fields: `BoundaryRanges`, `DensityFunction`, `isOutlier`.

#### LocalOutlierFactor

Local Outlier Factor (LOF). Compares local density of a point to its neighbors. Detects outliers in datasets with varying density.

```spl
| fit LocalOutlierFactor bytes packet_count into network_outlier_model n_neighbors=20
| fit LocalOutlierFactor feat1 feat2 feat3 contamination=0.05 into lof_model
```

Parameters: `n_neighbors` (default=20), `contamination` (expected outlier fraction), `algorithm` (auto, ball_tree, kd_tree), `metric`.

Output field: `isOutlier` (1 for outlier, 0 for inlier).

#### OneClassSVM

One-class Support Vector Machine. Learns boundary around normal data in high-dimensional space.

```spl
| fit OneClassSVM count dc_dest dc_app into uba_model kernel=rbf nu=0.05
```

Parameters: `kernel` (rbf, linear, poly, sigmoid), `nu` (upper bound on outlier fraction, default=0.5), `gamma`.

Output field: `isOutlier`.

#### IsolationForest

Isolates anomalies by randomly partitioning features. Efficient for high-dimensional data.

```spl
| fit IsolationForest feat1 feat2 feat3 contamination=0.1 into iso_forest_model n_estimators=100
```

Parameters: `n_estimators` (default=100), `contamination` (expected fraction of outliers), `max_features`, `random_state`.

Output field: `isOutlier`.

#### MultivariateOutlierDetection

Detects outliers across multiple dimensions simultaneously using Mahalanobis distance or similar metrics.

```spl
| fit MultivariateOutlierDetection bytes packets duration into multi_outlier_model
```

Output fields: `isOutlier`, `outlier_distance`.

#### EllipticEnvelope

Fits a Gaussian envelope around data and flags points outside as outliers. Assumes data is approximately Gaussian.

```spl
| fit EllipticEnvelope feat1 feat2 contamination=0.1 into envelope_model
```

Parameters: `contamination` (expected outlier fraction), `support_fraction`.

Output field: `isOutlier`.

---

### Time Series Forecasting

Algorithms for predicting future values of time series data.

#### ARIMA

AutoRegressive Integrated Moving Average. Standard time series forecasting model for stationary or trend-stationary data.

```spl
| timechart span=1h count | fit ARIMA count order=1-1-1 into hourly_forecast
| timechart span=1d count | fit ARIMA count order=5-1-0 holdback=30 into daily_forecast
```

Parameters: `order` (p-d-q: autoregressive order, differencing, moving average), `holdback` (validation points), `forecast_k` (steps to forecast), `conf_interval` (confidence level).

Output fields: `predicted(field)`, `lower95(predicted(field))`, `upper95(predicted(field))`.

#### StateSpaceForecast

State space model for time series with trend, seasonality, and noise components.

```spl
| timechart span=1h avg(cpu) | fit StateSpaceForecast avg_cpu into cpu_forecast forecast_k=24
```

Parameters: `forecast_k` (steps ahead), `holdback`, `conf_interval`, `period` (seasonal period).

#### KalmanFilter

Recursive Bayesian estimator for time series. Handles noisy observations with underlying state dynamics.

```spl
| timechart span=5m avg(latency) | fit KalmanFilter avg_latency into latency_kalman
```

Parameters: `forecast_k`, `holdback`.

---

### Feature Extraction and Preprocessing

Algorithms for transforming, reducing, or selecting features before modeling.

#### PCA - Principal Component Analysis

Reduces dimensionality by projecting data onto principal components that capture maximum variance.

```spl
| fit PCA feat1 feat2 feat3 feat4 feat5 k=3 into pca_model
| fit PCA "SS_*" k=10 into security_pca
```

Parameters: `k` (number of components to keep).

Output fields: `PC_1`, `PC_2`, ..., `PC_k`.

#### StandardScaler

Normalizes features to zero mean and unit variance. Critical for distance-based algorithms (KMeans, SVM, PCA).

```spl
| fit StandardScaler bytes packets duration into scaler_model
| apply scaler_model
| fit KMeans SS_bytes SS_packets SS_duration k=5 into scaled_clusters
```

Output fields: `SS_<fieldname>` (scaled versions of input fields).

#### FieldSelector

Selects the most relevant features based on statistical tests. Reduces noise and training time.

```spl
| fit FieldSelector target from feat1 feat2 feat3 feat4 feat5 type=categorical mode=include into selector_model
```

Parameters: `type` (categorical, numeric), `mode` (include, exclude), `param` (number of features to select).

#### TfidfVectorizer

Converts text fields into TF-IDF (Term Frequency-Inverse Document Frequency) numeric vectors for text-based ML.

```spl
| fit TfidfVectorizer message into tfidf_model max_features=1000
| apply tfidf_model
| fit LogisticRegression category from tfidf_* into text_classifier
```

Parameters: `max_features` (vocabulary size limit), `ngram_range`, `max_df`, `min_df`, `stop_words`.

#### NPR (Normalize, PCA, Reduce)

Combined preprocessing pipeline: normalize features, apply PCA, reduce to top components.

```spl
| fit NPR feat1 feat2 feat3 feat4 k=2 into npr_model
```

Parameters: `k` (number of output dimensions).

---

## Scoring Methods

### Classification Metrics

| Method | Description | Usage |
|--------|-------------|-------|
| `accuracy_score` | Fraction of correct predictions | `\| score accuracy_score actual against predicted(actual)` |
| `confusion_matrix` | Matrix of TP, FP, TN, FN per class | `\| score confusion_matrix actual against predicted(actual)` |
| `f1_score` | Harmonic mean of precision and recall | `\| score f1_score actual against predicted(actual) average=weighted` |
| `precision_recall_fscore_support` | Per-class precision, recall, F1, support | `\| score precision_recall_fscore_support actual against predicted(actual)` |
| `roc_auc_score` | Area under the ROC curve | `\| score roc_auc_score actual against predicted(actual)` |
| `log_loss` | Logarithmic loss (cross-entropy) | `\| score log_loss actual against predicted(actual)` |

### Regression Metrics

| Method | Description | Usage |
|--------|-------------|-------|
| `r2_score` | R-squared (coefficient of determination) | `\| score r2_score actual against predicted(actual)` |
| `mean_squared_error` | Mean squared error | `\| score mean_squared_error actual against predicted(actual)` |
| `mean_absolute_error` | Mean absolute error | `\| score mean_absolute_error actual against predicted(actual)` |

### Clustering Metrics

| Method | Description | Usage |
|--------|-------------|-------|
| `silhouette_score` | Measures cluster separation quality (-1 to 1) | `\| score silhouette_score cluster` |

---

## Smart Assistants

MLTK includes four guided assistants accessible from the MLTK app UI that automate common ML workflows.

### Smart Forecasting Assistant

Predicts future values of time series metrics. Automatically selects ARIMA or state space models, tunes parameters, and generates confidence intervals.

```
Use case: Capacity planning, SLA prediction, trend analysis
Input: Time series data (timechart output)
Output: Forecast with upper/lower confidence bounds
```

### Smart Outlier Detection Assistant

Identifies anomalous data points using density-based methods. Automatically selects thresholds and handles multivariate data.

```
Use case: Security alerting, performance monitoring, error detection
Input: Numeric fields to analyze
Output: isOutlier flag with outlier scores
```

### Smart Clustering Assistant

Groups similar events into clusters. Automatically determines optimal cluster count and algorithm.

```
Use case: User segmentation, log categorization, behavior grouping
Input: Numeric feature fields
Output: Cluster assignments with visualization
```

### Smart Prediction Assistant

Predicts categorical or numeric fields. Auto-selects classifier or regressor based on target field type and optimizes parameters.

```
Use case: Severity prediction, cost estimation, risk scoring
Input: Target field and feature fields
Output: Predicted values with confidence
```

---

## Security and SOC Use Cases

### Failed Login Anomaly Detection

Detect unusual spikes in authentication failures that may indicate brute force attacks or credential stuffing.

```spl
index=security sourcetype=auth action=failure
| timechart span=1h count as failed_logins
| fit DensityFunction failed_logins dist=norm threshold=0.005 into failed_login_anomaly
```

Apply the model in a scheduled saved search:

```spl
index=security sourcetype=auth action=failure
| timechart span=1h count as failed_logins
| apply failed_login_anomaly
| where isOutlier=1
```

### Network Traffic Anomaly Detection

Identify hosts generating unusual network traffic volumes that may indicate data exfiltration or C2 communication.

```spl
index=network sourcetype=firewall
| stats sum(bytes_out) as total_bytes dc(dest_ip) as unique_dests by src_ip
| fit LocalOutlierFactor total_bytes unique_dests n_neighbors=20 contamination=0.05 into network_outlier_model
```

### DNS Tunneling Detection

Detect potential DNS tunneling by analyzing query characteristics (length, entropy, frequency).

```spl
index=dns sourcetype=dns
| eval query_length=len(query)
| eval subdomain_count=mvcount(split(query, "."))
| stats avg(query_length) as avg_qlen dc(query) as unique_queries count by src_ip
| fit IsolationForest avg_qlen unique_queries count contamination=0.02 into dns_tunnel_model
```

### User Behavior Analytics (UBA)

Build behavioral baselines per user and flag deviations that may indicate compromised accounts or insider threats.

```spl
index=authentication sourcetype=auth action=success
| stats count as login_count dc(dest) as unique_hosts dc(app) as unique_apps dc(src) as unique_sources by user
| fit OneClassSVM login_count unique_hosts unique_apps unique_sources kernel=rbf nu=0.05 into uba_baseline
```

### Insider Threat Risk Clustering

Cluster users by behavior patterns to identify groups exhibiting high-risk activities.

```spl
index=dlp OR index=email OR index=web
| stats count as event_count dc(action) as action_types sum(bytes) as data_volume by user
| fit StandardScaler event_count action_types data_volume into insider_scaler
| apply insider_scaler
| fit KMeans SS_event_count SS_action_types SS_data_volume k=5 into insider_risk_clusters
```

### Domain Generation Algorithm (DGA) Detection

Classify DNS queries as potentially generated by malware DGA algorithms.

```spl
index=dns sourcetype=dns
| eval domain=lower(query)
| eval domain_length=len(domain)
| eval num_digits=len(replace(domain, "[^0-9]", ""))
| eval consonant_ratio=len(replace(domain, "[aeiouAEIOU0-9.\-]", ""))/domain_length
| eval digit_ratio=num_digits/domain_length
| fit RandomForestClassifier is_dga from domain_length consonant_ratio digit_ratio n_estimators=200 into dga_detector
```

### Rare Process Detection

Identify unusual processes running on endpoints that may indicate malware or unauthorized software.

```spl
index=endpoint sourcetype=sysmon EventCode=1
| stats count as exec_count dc(Computer) as host_spread by process_name
| fit LocalOutlierFactor exec_count host_spread n_neighbors=15 contamination=0.05 into rare_process_model
```

### Beaconing Detection

Detect periodic outbound communication patterns (beaconing) that may indicate C2 activity.

```spl
index=proxy sourcetype=web_proxy
| bin _time span=5m
| stats count as request_count by dest_ip _time
| streamstats window=12 stdev(request_count) as std_count avg(request_count) as avg_count by dest_ip
| eval cv=std_count/avg_count
| where cv < 0.2 AND avg_count > 5
```

For ARIMA-based beaconing forecasting:

```spl
index=proxy sourcetype=web_proxy dest_ip=<suspicious_ip>
| timechart span=5m count
| fit ARIMA count order=1-0-0 into beacon_check
```

### Lateral Movement Detection

Detect potential lateral movement by identifying users accessing unusual hosts.

```spl
index=authentication sourcetype=wineventlog EventCode=4624
| stats dc(dest) as unique_dests values(dest) as dests by src_user
| fit IsolationForest unique_dests contamination=0.05 into lateral_movement_model
```

---

## Complete Workflow Examples

### End-to-End Classification Pipeline

```spl
... Step 1: Prepare and sample data
index=security sourcetype=auth
| stats count dc(dest) dc(src) values(action) as actions by user
| eval is_suspicious=if(match(actions, "failure") AND count > 50, 1, 0)
| sample partitions=5 seed=42

... Step 2: Train on partitions 0-3
| where partition_number <= 3
| fit StandardScaler count dc_dest dc_src into auth_scaler
| apply auth_scaler
| fit RandomForestClassifier is_suspicious from SS_count SS_dc_dest SS_dc_src into auth_classifier n_estimators=100

... Step 3: Validate on partition 4
| where partition_number = 4
| apply auth_scaler
| apply auth_classifier
| score accuracy_score is_suspicious against predicted(is_suspicious)
| score confusion_matrix is_suspicious against predicted(is_suspicious)
```

### End-to-End Anomaly Detection Pipeline

```spl
... Step 1: Build baseline
index=network sourcetype=firewall earliest=-30d latest=-1d
| stats sum(bytes) as total_bytes dc(dest_port) as port_count avg(duration) as avg_duration by src_ip
| fit StandardScaler total_bytes port_count avg_duration into network_scaler
| apply network_scaler
| fit IsolationForest SS_total_bytes SS_port_count SS_avg_duration contamination=0.05 into network_anomaly

... Step 2: Apply to current data (scheduled search)
index=network sourcetype=firewall earliest=-1h
| stats sum(bytes) as total_bytes dc(dest_port) as port_count avg(duration) as avg_duration by src_ip
| apply network_scaler
| apply network_anomaly
| where isOutlier=1
| table src_ip total_bytes port_count avg_duration
```

### End-to-End Forecasting Pipeline

```spl
... Step 1: Train forecast model
index=infrastructure sourcetype=cpu earliest=-90d
| timechart span=1d avg(cpu_percent) as avg_cpu
| fit ARIMA avg_cpu order=5-1-1 holdback=14 forecast_k=30 conf_interval=95 into cpu_forecast

... Step 2: Apply and alert on threshold
index=infrastructure sourcetype=cpu earliest=-90d
| timechart span=1d avg(cpu_percent) as avg_cpu
| apply cpu_forecast
| where predicted(avg_cpu) > 85
```

---

## Best Practices

### Data Preparation

1. **Always create train/test splits** using `| sample partitions=5 seed=42` for reproducible evaluation.
2. **Scale features** with `StandardScaler` before distance-based algorithms (KMeans, SVM, PCA, KNN).
3. **Use PCA** for dimensionality reduction when working with high-dimensional feature spaces (50+ fields).
4. **Handle missing values** before training. Use `fillnull` or `where isnotnull(field)` to clean data.
5. **Balance classes** for classification. Heavily imbalanced classes lead to biased models.

### Model Selection

6. **Start simple**. Use LogisticRegression or LinearRegression as baselines before trying complex models.
7. **Use AutoPrediction** when unsure which algorithm fits. It tests multiple and selects the best.
8. **Match algorithm to task**: classifiers for categories, regressors for numbers, clustering for grouping, anomaly detection for outliers.

### Validation

9. **Always validate** with `| score` on held-out test data, not training data.
10. **Use cross-validation** via `sample partitions=5` and average metrics across folds.
11. **Check multiple metrics**. Accuracy alone is misleading for imbalanced data; use F1, precision/recall, and confusion matrix.

### Production Deployment

12. **Train offline, apply in real-time**. Use `fit` in ad-hoc searches, `apply` in scheduled saved searches and alerts.
13. **Retrain periodically**. Schedule model retraining (weekly/monthly) to prevent concept drift.
14. **Model storage**. Models are stored in `$SPLUNK_HOME/etc/apps/Splunk_ML_Toolkit/lookups/`. Back up models before retraining.
15. **Use CIM-normalized data** for security use cases. The Common Information Model ensures consistent field names across sourcetypes.

### Performance

16. **Sample large datasets** before training. Most algorithms do not need millions of events to learn patterns.
17. **Limit features**. Use `FieldSelector` or domain knowledge to reduce features to the most relevant.
18. **Use MiniBatchKMeans** instead of KMeans for very large datasets.
19. **Set `random_state` or `seed`** for reproducible results across runs.

---

## Model Management

### Listing and Inspecting Models

```spl
| listmodels
| summary my_model_name
```

### Deleting Old Models

```spl
| deletemodel deprecated_model_v1
```

### Model Versioning Pattern

Use naming conventions to version models:

```spl
| fit LogisticRegression target from features into threat_model_v2_20260101
```

### Retraining Schedule

Set up a scheduled saved search to retrain models periodically:

```spl
index=security sourcetype=auth earliest=-30d
| stats count dc(dest) dc(src) by user action
| fit RandomForestClassifier action from count dc_dest dc_src into auth_model_latest n_estimators=100
```

---

## Python for Scientific Computing (PSC)

The Python for Scientific Computing add-on extends MLTK with 300+ additional algorithms from scikit-learn, statsmodels, scipy, and other libraries. Install from Splunkbase to access the full algorithm catalog.

Key additional algorithms available via PSC:
- **XGBClassifier / XGBRegressor** - XGBoost gradient boosting
- **LightGBM** - Light Gradient Boosting Machine
- **CatBoost** - Categorical boosting
- **HDBSCAN** - Hierarchical DBSCAN
- **t-SNE** - t-distributed Stochastic Neighbor Embedding (visualization)
- **UMAP** - Uniform Manifold Approximation (visualization/reduction)
- Additional preprocessing, feature selection, and scoring methods

---

## Troubleshooting

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `Model not found` | Model name typo or not yet trained | Run `\| listmodels` to check; retrain with `fit` |
| `Field not found` | Feature field missing from data | Verify field exists with `\| fields` or `\| fieldsummary` |
| `Insufficient data` | Too few events for algorithm | Increase time range or reduce `min_samples` |
| `Memory error` | Dataset too large | Use `\| sample` to reduce data or use MiniBatchKMeans |
| `Convergence warning` | Algorithm did not converge | Increase `max_iter` or adjust regularization |

### Performance Tips

- Use `| head 100000` or `| sample ratio=0.1` during model development to speed up iteration.
- For production, train on full representative data.
- Monitor model training time in the job inspector.
- Consider using summary indexing (`collect`) to pre-aggregate features for faster model training.
