"""JARVIS AI/ML Knowledge Base — zero-API keyword fallback. Ordered most-specific first."""

AIML_KNOWLEDGE = {

    # ── Specific algorithms ──────────────────────────────────────────────────────
    "k-nearest neighbor": (
        "KNN classifies new data by finding the K closest training examples using distance "
        "metrics (Euclidean, Manhattan). No training phase — predictions at query time "
        "(lazy learner). Key param: K. Sensitive to scale, always normalise features. "
        "Used in recommendation systems, anomaly detection, and image classification."
    ),
    "knn": (
        "KNN (K-Nearest Neighbor) classifies by majority vote among K nearest neighbors. "
        "Simple, no training required. Always normalise data first. "
        "Choosing K: small K = complex boundary, large K = smoother boundary."
    ),
    "support vector machine": (
        "SVM finds the maximum-margin hyperplane separating classes. Support vectors are "
        "the closest data points to the boundary. The kernel trick (RBF, Polynomial) "
        "handles non-linear problems. Effective for high-dimensional small datasets "
        "like text classification and bioinformatics."
    ),
    "svm": (
        "SVM (Support Vector Machine) maximises the margin between classes. "
        "Kernels (RBF, Polynomial, Linear) enable non-linear classification. "
        "Used in text categorisation, image recognition, and gene expression analysis."
    ),
    "random forest": (
        "Random Forest builds many decision trees on random data and feature subsets, "
        "then combines predictions by voting (classification) or averaging (regression). "
        "Reduces overfitting vs single trees, provides feature importance scores. "
        "Used in fraud detection, medical diagnosis, and stock prediction."
    ),
    "gradient boosting": (
        "Gradient Boosting builds trees sequentially — each new tree corrects the "
        "previous ensemble's errors by fitting residuals. Implementations: XGBoost, "
        "LightGBM, CatBoost. Among the most powerful algorithms for tabular data. "
        "Dominant in Kaggle competitions and financial modelling."
    ),
    "xgboost": (
        "XGBoost (Extreme Gradient Boosting) is an optimised gradient boosting library "
        "with L1/L2 regularisation, parallel tree construction, and sparse data handling. "
        "Faster and more accurate than vanilla gradient boosting. "
        "One of the most used algorithms in data science competitions."
    ),
    "lightgbm": (
        "LightGBM is a fast gradient boosting framework using leaf-wise tree growth and "
        "histogram-based algorithms. Faster and more memory-efficient than XGBoost "
        "for large datasets. Excellent for high-cardinality categorical features."
    ),
    "decision tree": (
        "A Decision Tree splits data on feature thresholds forming a tree of decisions. "
        "Leaf nodes are predictions. Easy to interpret but prone to overfitting — "
        "solved by pruning or using Random Forest. Algorithms: CART, ID3, C4.5. "
        "Used in loan approval, medical diagnosis, and customer segmentation."
    ),
    "naive bayes": (
        "Naive Bayes applies Bayes Theorem assuming feature independence. Despite this "
        "simplification it excels at text tasks. Variants: Gaussian (continuous), "
        "Multinomial (word counts), Bernoulli (binary). Very fast. "
        "Used in spam filtering, news categorisation, and sentiment analysis."
    ),
    "k-means": (
        "K-Means clusters data into K groups by iteratively assigning points to the "
        "nearest centroid and recomputing centroids until convergence. "
        "Use the Elbow Method to choose K. "
        "Used in customer segmentation, image compression, and anomaly detection."
    ),
    "dbscan": (
        "DBSCAN clusters data based on density and identifies outliers as noise. "
        "Does not require specifying K upfront. Finds arbitrarily shaped clusters. "
        "Two parameters: epsilon (neighborhood radius) and minPts (minimum points). "
        "Used in geospatial analysis and anomaly detection."
    ),
    "principal component analysis": (
        "PCA reduces dimensionality by projecting data onto directions of maximum "
        "variance (principal components). Removes correlated features and noise. "
        "Steps: standardise data, compute covariance matrix, find eigenvectors, "
        "select top components. Used in visualisation, face recognition, genomics."
    ),
    "pca": (
        "PCA (Principal Component Analysis) transforms correlated features into "
        "uncorrelated principal components capturing maximum variance. "
        "Key technique for dimensionality reduction, noise removal, and visualisation. "
        "First component explains the most variance, second the next most, etc."
    ),
    "linear regression": (
        "Linear Regression models relationships as y = mx + b, minimising squared errors "
        "(Ordinary Least Squares). Simple (one feature) and Multiple (many features). "
        "Assumptions: linearity, independence, homoscedasticity, normality of residuals. "
        "Used in price prediction, trend analysis, and demand forecasting."
    ),
    "logistic regression": (
        "Logistic Regression predicts probability of binary outcomes using the sigmoid "
        "function: output between 0 and 1. Uses log-loss (cross-entropy). "
        "L1/L2 regularisation prevents overfitting. Extended to multi-class via softmax. "
        "Used in medical diagnosis, credit scoring, and spam detection."
    ),
    "apriori": (
        "Apriori is an association rule learning algorithm finding frequent itemsets "
        "in transaction data. Generates rules like 'if A then B' with support, "
        "confidence, and lift metrics. Used in market basket analysis and "
        "recommendation systems."
    ),

    # ── Neural architectures ─────────────────────────────────────────────────────
    "convolutional neural network": (
        "CNNs use convolutional filters to detect features (edges, textures, shapes) "
        "hierarchically. Layers: Convolutional, Pooling, Fully Connected. "
        "Translation-invariant. Famous architectures: VGG, ResNet, MobileNet, EfficientNet. "
        "Dominant in image classification, object detection, and medical imaging."
    ),
    "recurrent neural network": (
        "RNNs process sequences by maintaining a hidden state capturing previous inputs. "
        "Problem: vanishing gradient on long sequences — solved by LSTM and GRU. "
        "Used in language modelling, machine translation, speech recognition, "
        "and time series forecasting."
    ),
    "long short-term memory": (
        "LSTM solves the RNN vanishing gradient problem via three gates: "
        "Forget (what to discard), Input (new information), Output (what to expose). "
        "A cell state acts as long-term memory across many time steps. "
        "Used in machine translation, text generation, and stock prediction."
    ),
    "lstm": (
        "LSTM (Long Short-Term Memory) maintains long-term sequence dependencies "
        "using Forget, Input, and Output gates plus a cell state. "
        "Outperforms standard RNNs on long sequences. "
        "Used in NLP, speech recognition, and time series forecasting."
    ),
    "gru": (
        "GRU (Gated Recurrent Unit) is a simplified LSTM with two gates: Reset and Update. "
        "Fewer parameters than LSTM with similar performance. Faster to train. "
        "Good alternative when computational resources are limited."
    ),
    "generative adversarial network": (
        "GANs pit a Generator (creates fake data) against a Discriminator (detects fakes). "
        "Competition drives the generator to produce increasingly realistic outputs. "
        "Variants: DCGAN, StyleGAN, CycleGAN, Pix2Pix. "
        "Used in image synthesis, data augmentation, deepfakes, and art generation."
    ),
    "gan": (
        "A GAN has two networks: Generator (synthesises data) and Discriminator "
        "(distinguishes real from fake). Trained adversarially. "
        "Produces realistic images, videos, and audio. "
        "Variants: StyleGAN (faces), CycleGAN (style transfer)."
    ),
    "autoencoder": (
        "Autoencoders encode input to a compressed bottleneck then reconstruct it. "
        "Forces learning of key features. Variants: Denoising (trained on noisy input), "
        "Variational/VAE (generative, samples from learned distribution). "
        "Used in anomaly detection, denoising, and dimensionality reduction."
    ),
    "variational autoencoder": (
        "VAEs encode inputs as distributions (mean + variance) rather than fixed vectors. "
        "Enables sampling new realistic data from the learned distribution. "
        "Combines autoencoder structure with variational Bayesian inference. "
        "Used in image generation and drug discovery."
    ),
    "bert": (
        "BERT (Bidirectional Encoder Representations from Transformers) by Google (2018) "
        "reads text bidirectionally, capturing full context from both directions. "
        "Pre-trained on Masked Language Modelling and Next Sentence Prediction. "
        "Fine-tuned for QA, NER, and text classification. Set records on 11 NLP benchmarks."
    ),
    "gpt": (
        "GPT (Generative Pre-trained Transformer) is a decoder-only Transformer "
        "trained to predict the next token. GPT-3 has 175B parameters; GPT-4 is multimodal. "
        "Powers ChatGPT. Uses RLHF for alignment. "
        "Used for text generation, code, summarisation, and reasoning."
    ),
    "attention mechanism": (
        "Attention allows networks to focus on relevant input positions dynamically. "
        "Self-Attention: every token attends to all others, capturing long-range dependencies. "
        "Multi-Head Attention runs attention in parallel across multiple subspaces. "
        "Foundation of the Transformer and all modern LLMs."
    ),
    "resnet": (
        "ResNet (Residual Network) uses skip connections that add layer input directly "
        "to layer output, solving vanishing gradients in very deep networks. "
        "ResNet-50/101/152 are standard CV baselines. "
        "Enabled training of networks with 100+ layers reliably."
    ),
    "yolo": (
        "YOLO (You Only Look Once) performs object detection in a single forward pass, "
        "making it extremely fast for real-time applications. "
        "Divides image into grid cells, each predicting bounding boxes and class probabilities. "
        "YOLOv8 is the current state-of-the-art version."
    ),

    # ── Training concepts ─────────────────────────────────────────────────────────
    "activation function": (
        "Activation functions introduce non-linearity into neural networks. "
        "ReLU: max(0,x) — most common, fast. Sigmoid: 0 to 1 (binary output). "
        "Tanh: -1 to 1. Softmax: multi-class probabilities. Leaky ReLU: fixes dying ReLU. "
        "Without activation functions, networks can only compute linear transformations."
    ),
    "backpropagation": (
        "Backpropagation computes weight gradients using the chain rule of calculus. "
        "Steps: 1) Forward pass (compute predictions), 2) Compute loss, "
        "3) Backward pass (propagate error through layers), "
        "4) Update weights via gradient descent. Core training algorithm for neural nets."
    ),
    "gradient descent": (
        "Gradient Descent minimises loss by stepping in the negative gradient direction. "
        "Variants: Batch GD (all data), SGD (one sample), Mini-Batch GD (small batches). "
        "Advanced optimisers: Adam (adaptive + momentum), RMSprop, AdaGrad. "
        "Learning rate controls step size."
    ),
    "learning rate": (
        "Learning rate controls how much weights update per step. "
        "Too high: training diverges. Too low: very slow convergence. "
        "Techniques: LR scheduling, warm restarts, cyclic LR. "
        "Adam optimiser adapts LR per parameter automatically."
    ),
    "batch normalization": (
        "Batch Normalisation normalises layer inputs to zero mean and unit variance "
        "within each mini-batch. Benefits: faster training (allows higher LR), "
        "reduces sensitivity to weight initialisation, mild regularisation effect. "
        "Applied before or after the activation function."
    ),
    "dropout": (
        "Dropout zeros random neurons during training at a given rate (0.2-0.5), "
        "preventing co-adaptation and forcing redundant representations. "
        "At inference all neurons are active. Effectively trains an ensemble of "
        "sub-networks. Major regularisation technique in deep learning."
    ),
    "overfitting": (
        "Overfitting: model memorises training data including noise, fails on new data. "
        "Symptom: low training loss, high validation loss. "
        "Prevention: Dropout, L1/L2 regularisation, early stopping, "
        "data augmentation, cross-validation, collecting more data."
    ),
    "underfitting": (
        "Underfitting: model too simple to capture data patterns. "
        "Symptom: high loss on both training and test sets (high bias). "
        "Fix: increase model complexity, add more features, reduce regularisation, "
        "train for more epochs, use a more powerful algorithm."
    ),
    "regularization": (
        "Regularisation penalises model complexity to prevent overfitting. "
        "L1 (Lasso): adds |weights| to loss, promotes sparsity, performs feature selection. "
        "L2 (Ridge): adds weights squared, shrinks all weights. "
        "Elastic Net: combines L1 and L2. Other: Dropout, Early Stopping."
    ),
    "early stopping": (
        "Early Stopping halts training when validation loss stops improving. "
        "Patience parameter controls how many epochs to wait. "
        "Always save the best checkpoint, not the final model. "
        "Simple, effective regularisation that requires no model modification."
    ),
    "hyperparameter": (
        "Hyperparameters are settings chosen before training: learning rate, batch size, "
        "number of layers, dropout rate, regularisation strength, number of trees. "
        "Tuning methods: Grid Search, Random Search, Bayesian Optimisation (Optuna). "
        "Different from model parameters which are learned during training."
    ),
    "weight initialization": (
        "Weight initialisation affects training convergence. Xavier/Glorot: for sigmoid/tanh. "
        "He initialisation: for ReLU networks. Random small values avoid symmetry breaking. "
        "Poor initialisation causes vanishing or exploding gradients, "
        "stalling or destabilising training."
    ),

    # ── Learning paradigms ────────────────────────────────────────────────────────
    "supervised learning": (
        "Supervised Learning trains on labelled input-output pairs, learning to predict "
        "outputs for new inputs. Types: Classification (discrete output — spam/not spam) "
        "and Regression (continuous output — house price). "
        "Algorithms: Logistic Regression, SVM, Random Forest, Neural Networks."
    ),
    "unsupervised learning": (
        "Unsupervised Learning finds hidden patterns in unlabelled data. "
        "Tasks: Clustering (K-Means, DBSCAN, Hierarchical), "
        "Dimensionality Reduction (PCA, t-SNE, UMAP), Association (Apriori). "
        "Used in customer segmentation, anomaly detection, and data exploration."
    ),
    "reinforcement learning": (
        "RL trains an agent to maximise cumulative reward through environment interaction. "
        "Key concepts: State, Action, Reward, Policy, Value Function, Q-function. "
        "Algorithms: Q-Learning, DQN, PPO, SAC, A3C. "
        "Achievements: AlphaGo, ChatGPT (RLHF), robotics, game-playing AI."
    ),
    "semi-supervised": (
        "Semi-Supervised Learning combines small labelled datasets with large unlabelled ones. "
        "Labelled data is expensive; unlabelled is abundant. "
        "Techniques: self-training, co-training, label propagation. "
        "Used in medical imaging and NLP where annotation is costly."
    ),
    "transfer learning": (
        "Transfer Learning reuses a pre-trained model as a starting point for a new task. "
        "Freeze early layers (general features), fine-tune later ones (task-specific). "
        "Dramatically reduces data and compute requirements. "
        "Examples: fine-tune BERT for sentiment analysis, ResNet for medical imaging."
    ),
    "self-supervised learning": (
        "Self-Supervised Learning generates supervision signals from the data itself. "
        "Examples: predicting masked words (BERT), next-token prediction (GPT), "
        "contrastive learning (SimCLR, CLIP). Enables training on vast unlabelled data. "
        "Foundation of modern LLMs."
    ),
    "federated learning": (
        "Federated Learning trains models across many devices without sharing raw data. "
        "Only model updates (gradients) are sent to a central server. Preserves privacy. "
        "Used in Google Gboard keyboard prediction and healthcare research "
        "where hospitals cannot share patient data."
    ),
    "few-shot learning": (
        "Few-Shot Learning generalises from very few labelled examples (1 to 10 per class). "
        "Techniques: Meta-Learning, Siamese Networks, Prototypical Networks. "
        "LLMs like GPT-4 demonstrate strong few-shot ability from prompting alone. "
        "Critical when labelled data is scarce."
    ),

    # ── Evaluation metrics ────────────────────────────────────────────────────────
    "confusion matrix": (
        "A Confusion Matrix shows TP, TN, FP (Type I error), FN (Type II error). "
        "Accuracy = (TP+TN)/total. Precision = TP/(TP+FP). Recall = TP/(TP+FN). "
        "F1 = harmonic mean of Precision and Recall. "
        "Essential for evaluating classifiers on imbalanced datasets."
    ),
    "f1 score": (
        "F1 = 2 * (Precision * Recall) / (Precision + Recall). "
        "Harmonic mean balancing both metrics. Range: 0 (worst) to 1 (best). "
        "More informative than accuracy for imbalanced classes. "
        "Macro F1: equal weight per class; Weighted F1: weighted by support."
    ),
    "roc curve": (
        "ROC plots True Positive Rate vs False Positive Rate across all thresholds. "
        "AUC (Area Under Curve): 1.0 = perfect classifier, 0.5 = random. "
        "Higher AUC = better class separation. "
        "Use Precision-Recall curves for highly imbalanced datasets."
    ),
    "mean squared error": (
        "MSE = mean of squared differences between predictions and actuals. "
        "RMSE = sqrt(MSE) in the same units as the target variable. "
        "MAE = mean absolute error, more robust to outliers. "
        "R-squared measures explained variance: 1 = perfect, 0 = predicts mean only."
    ),
    "precision": (
        "Precision = TP / (TP + FP) — of all predicted positives, how many are correct. "
        "High precision means few false alarms. "
        "Important when false positives are costly, e.g., spam filtering."
    ),
    "recall": (
        "Recall = TP / (TP + FN) — of all actual positives, how many were detected. "
        "High recall means few missed positives. "
        "Critical when missing a case is costly, e.g., cancer screening or fraud."
    ),

    # ── Data concepts ─────────────────────────────────────────────────────────────
    "feature engineering": (
        "Feature Engineering transforms raw data into informative model inputs. "
        "Techniques: date decomposition, log/polynomial transforms, interaction terms, "
        "TF-IDF, one-hot encoding, binning numerical values. "
        "Often more impactful than algorithm choice. Requires domain knowledge."
    ),
    "feature selection": (
        "Feature Selection removes irrelevant/redundant features. "
        "Filter methods: chi-square, correlation, mutual information. "
        "Wrapper: recursive feature elimination (RFE). "
        "Embedded: Lasso coefficients, tree feature_importances_. "
        "Reduces noise, speeds training, and improves generalisation."
    ),
    "data preprocessing": (
        "Data Preprocessing prepares raw data for ML. Steps: handle missing values "
        "(mean/median imputation or removal), encode categoricals (one-hot/label), "
        "scale features (StandardScaler/MinMaxScaler), remove outliers, "
        "engineer features, split into train/validation/test sets."
    ),
    "normalization": (
        "Feature Scaling ensures features are on a comparable scale. "
        "Min-Max Normalisation: scales to [0,1]. StandardScaler (Z-score): mean=0, std=1. "
        "Robust Scaler: uses IQR, resistant to outliers. "
        "Required for KNN, SVM, Neural Networks. Tree models do not require scaling."
    ),
    "one hot encoding": (
        "One-Hot Encoding converts categories into binary columns, one per category. "
        "Example: Color {R,G,B} becomes [1,0,0], [0,1,0], [0,0,1]. "
        "Prevents the model from assuming ordinal relationships. "
        "Use with care for high-cardinality features. Alternatives: Label, Target Encoding."
    ),
    "cross-validation": (
        "K-Fold Cross-Validation splits data into K folds; each fold is used as "
        "validation once while the rest train. Stratified K-Fold preserves class balance. "
        "Final score is the average across all folds, giving reliable performance estimates. "
        "Prevents overly optimistic single-split evaluations."
    ),
    "bias-variance": (
        "Bias-Variance Tradeoff: Total Error = Bias squared + Variance + Irreducible Noise. "
        "Bias (underfitting): wrong assumptions, model too simple. "
        "Variance (overfitting): sensitivity to training data fluctuations, model too complex. "
        "Regularisation reduces variance; complexity/features reduce bias."
    ),
    "train test split": (
        "Train-Test Split: 70-80% for training, 20-30% for testing. "
        "Model learns on train, evaluated on unseen test data. "
        "Validation set (from train) used for hyperparameter tuning. "
        "sklearn: train_test_split(X, y, test_size=0.2, random_state=42)."
    ),
    "imbalanced data": (
        "Imbalanced datasets have unequal class distribution (e.g., 99% negative, 1% positive). "
        "Techniques: Oversampling (SMOTE), Undersampling, Class weights in loss function. "
        "Evaluate with F1, AUC-ROC rather than raw accuracy. "
        "Anomaly detection approach works well for extreme imbalance."
    ),
    "data augmentation": (
        "Data Augmentation artificially expands training data with transformations. "
        "Vision: flip, crop, rotate, colour jitter, cutout, mixup. "
        "NLP: synonym replacement, back-translation, paraphrasing. "
        "Reduces overfitting, especially on small datasets."
    ),

    # ── Python ML libraries ───────────────────────────────────────────────────────
    "scikit-learn": (
        "Scikit-learn is Python's primary ML library with a consistent fit/predict/transform "
        "API. Provides classifiers, regressors, clusterers, preprocessors, "
        "GridSearchCV, cross_val_score, and Pipelines. "
        "Built on NumPy/SciPy. Install: pip install scikit-learn."
    ),
    "sklearn": (
        "sklearn (scikit-learn) key modules: linear_model, ensemble, svm, preprocessing, "
        "model_selection, metrics. Unified API — every estimator has fit() and predict(). "
        "Foundation of classical ML in Python, used by millions of data scientists."
    ),
    "tensorflow": (
        "TensorFlow by Google: tf.keras high-level API, tf.data for data pipelines, "
        "TensorBoard for visualisation, TF Lite for mobile, TF Serving for production. "
        "Supports GPU and TPU acceleration. Version 2.x uses eager execution by default."
    ),
    "pytorch": (
        "PyTorch by Meta uses dynamic computation graphs, making debugging intuitive. "
        "Key modules: torch.nn, torch.optim, torch.utils.data (DataLoader). "
        "PyTorch Lightning simplifies training loops. "
        "Preferred in research. Supports CUDA GPU acceleration."
    ),
    "keras": (
        "Keras (now tf.keras) provides Sequential and Functional APIs for building "
        "neural networks quickly. Key layers: Dense, Conv2D, LSTM, Dropout, "
        "BatchNormalization. Makes prototyping fast and readable. "
        "Supports callbacks: EarlyStopping, ModelCheckpoint, TensorBoard."
    ),
    "pandas": (
        "Pandas is Python's primary data analysis library. "
        "Key structures: DataFrame (2D table) and Series (1D). "
        "Operations: read_csv, dropna/fillna, groupby, merge, pivot_table. "
        "Essential for ML data preprocessing. Import: import pandas as pd."
    ),
    "numpy": (
        "NumPy provides N-dimensional arrays with vectorised operations. "
        "Key: array operations, np.linalg (linear algebra), np.random (sampling). "
        "Backbone of all Python ML/data science libraries. "
        "Import: import numpy as np. Arrays are much faster than Python lists."
    ),
    "matplotlib": (
        "Matplotlib is Python's standard visualisation library. "
        "Creates line, scatter, bar, histogram, and heatmap plots. "
        "Seaborn (built on Matplotlib) provides better statistical defaults. "
        "Usage: import matplotlib.pyplot as plt; plt.plot(); plt.show()."
    ),
    "opencv": (
        "OpenCV (cv2) is the leading computer vision library for Python, C++, Java. "
        "Operations: image read/write, resize, blur, edge detection (Canny), "
        "face detection (Haar cascades), object tracking, DNN inference. "
        "Import: import cv2."
    ),
    "hugging face": (
        "Hugging Face hosts 100,000+ pre-trained models (BERT, GPT, LLaMA, Mistral). "
        "Transformers library: AutoTokenizer, AutoModel, pipeline() for quick inference. "
        "Datasets library for efficient data loading. PEFT for LoRA fine-tuning. "
        "The go-to platform for all modern NLP and LLM work."
    ),
    "seaborn": (
        "Seaborn is a statistical visualisation library built on Matplotlib. "
        "Provides attractive defaults for heatmaps, violin plots, pair plots, and "
        "regression plots. Excellent for exploratory data analysis. "
        "Import: import seaborn as sns."
    ),

    # ── Real-world applications ───────────────────────────────────────────────────
    "speech recognition": (
        "Speech Recognition converts spoken audio to text. "
        "Pipeline: audio to MFCC features to model to text. "
        "Technologies: HMM (traditional), LSTM, Transformers (Whisper, Wav2Vec 2.0). "
        "Products: Google Speech-to-Text, AWS Transcribe, Siri, Alexa."
    ),
    "recommendation system": (
        "Recommendation Systems suggest relevant items to users. "
        "Approaches: Collaborative Filtering (user-item interactions), "
        "Content-Based (item features), Hybrid, Matrix Factorisation (SVD). "
        "Used in Netflix, Spotify, Amazon, YouTube. Metrics: RMSE, Precision@K, NDCG."
    ),
    "fraud detection": (
        "Fraud Detection uses ML to flag fraudulent transactions in real time. "
        "Algorithms: Logistic Regression, XGBoost, Autoencoders (anomaly detection). "
        "Challenge: extreme class imbalance. Handle with SMOTE and class weights. "
        "Deployed at PayPal, Visa, and banks worldwide."
    ),
    "sentiment analysis": (
        "Sentiment Analysis classifies text as positive, negative, or neutral. "
        "Traditional: Bag-of-Words + Naive Bayes/Logistic Regression. "
        "State-of-the-art: fine-tuned BERT/RoBERTa. "
        "Used in product reviews, social media monitoring, and brand analysis."
    ),
    "object detection": (
        "Object Detection locates and classifies multiple objects with bounding boxes. "
        "Algorithms: Faster R-CNN (accurate), YOLO (real-time), SSD, DETR (Transformer). "
        "Metric: mAP (mean Average Precision). "
        "Used in autonomous vehicles, security cameras, and robotics."
    ),
    "autonomous vehicle": (
        "Self-driving cars use AI for Perception (cameras, LiDAR), Localisation, "
        "Prediction (other agents), Planning (path), and Control. "
        "AI: CNNs (detection), LSTMs (trajectory), RL (decision making). "
        "SAE Levels 0-5. Companies: Waymo, Tesla, Cruise."
    ),
    "image recognition": (
        "Image Recognition assigns labels to whole images. "
        "CNNs revolutionised this in 2012 (AlexNet on ImageNet). "
        "Modern architectures: ResNet, EfficientNet, Vision Transformer (ViT). "
        "Transfer learning from ImageNet weights is standard practice."
    ),
    "named entity recognition": (
        "NER identifies and classifies entities in text: persons, organisations, "
        "locations, dates, monetary values. "
        "Models: CRF (traditional), BiLSTM-CRF, fine-tuned BERT (state-of-the-art). "
        "Library: spaCy. Used in information extraction and search."
    ),
    "machine translation": (
        "Machine Translation converts text between languages. "
        "Evolution: Rule-based to Statistical (phrase-based SMT) to "
        "Neural (seq2seq with attention) to Transformers (Google Translate, DeepL). "
        "Evaluation metric: BLEU score."
    ),

    # ── MLOps and deployment ──────────────────────────────────────────────────────
    "mlops": (
        "MLOps applies DevOps principles to ML: data versioning (DVC), "
        "experiment tracking (MLflow, Weights and Biases), model registry, "
        "CI/CD for ML pipelines, deployment (Docker, Kubernetes), "
        "monitoring (data drift, model performance degradation)."
    ),
    "model deployment": (
        "Model Deployment methods: REST API (Flask/FastAPI), batch inference, "
        "real-time streaming (Kafka), edge/mobile (TF Lite, CoreML). "
        "Tools: Docker, Kubernetes, AWS SageMaker, Google Vertex AI. "
        "Key concerns: latency, throughput, model versioning, A/B testing."
    ),
    "explainable ai": (
        "XAI makes model decisions interpretable. "
        "LIME: locally approximates the model around a prediction. "
        "SHAP: assigns feature importance using Shapley values from game theory. "
        "Attention maps for Transformers. Saliency maps for CNNs. "
        "Required for healthcare, finance, and GDPR compliance."
    ),
    "generative ai": (
        "Generative AI creates new content: text (GPT-4, Gemini), images (DALL-E, "
        "Stable Diffusion), audio, video (Sora), and code (Copilot). "
        "Architectures: GANs, VAEs, Diffusion Models, LLMs. "
        "Raises concerns about deepfakes, copyright, and hallucinations."
    ),
    "diffusion model": (
        "Diffusion Models learn to reverse a gradual Gaussian noising process. "
        "Forward: add noise step by step. Reverse: neural network predicts and removes noise. "
        "State-of-the-art image quality. Examples: Stable Diffusion, DALL-E 2, Midjourney. "
        "More stable to train than GANs."
    ),
    "data science": (
        "Data Science extracts insights from data using statistics, mathematics, and ML. "
        "Workflow: Define problem, Collect data, EDA, Preprocess, Model, Evaluate, "
        "Deploy, Monitor. Tools: Python, SQL, Jupyter, Tableau. "
        "Roles: Data Analyst, Data Scientist, ML Engineer, Data Engineer."
    ),

    # ── Broad foundational topics — most general, placed last ────────────────────
    "large language model": (
        "LLMs are neural networks with billions of parameters trained on massive text. "
        "Architecture: Transformer (decoder-only for GPT, encoder-decoder for T5). "
        "Training: pre-training then instruction fine-tuning and RLHF alignment. "
        "Examples: GPT-4, Gemini, LLaMA, Claude, Mistral. Capabilities: text, code, reasoning."
    ),
    "transformer": (
        "Transformer (2017, Attention Is All You Need) replaced RNNs for sequences. "
        "Self-Attention: every token attends to all others, capturing long-range dependencies. "
        "Components: Multi-Head Attention, Feed-Forward, LayerNorm, Positional Encoding. "
        "Encoder-only (BERT), Decoder-only (GPT), Encoder-Decoder (T5, BART)."
    ),
    "natural language processing": (
        "NLP enables computers to understand and generate human language. "
        "Tasks: tokenisation, POS tagging, NER, sentiment analysis, translation, "
        "summarisation, question answering. Modern NLP uses Transformers: BERT (understanding), "
        "GPT (generation). Libraries: NLTK, spaCy, Hugging Face Transformers."
    ),
    "computer vision": (
        "Computer Vision enables machines to interpret images and video. "
        "Tasks: Classification, Object Detection (YOLO, Faster R-CNN), Segmentation, "
        "Face Recognition, OCR, Pose Estimation. CNNs dominated 2012-2020. "
        "Vision Transformers (ViT) now compete. Libraries: OpenCV, torchvision."
    ),
    "deep learning": (
        "Deep Learning uses multi-layer neural networks to learn hierarchical "
        "representations from raw data automatically, without manual feature engineering. "
        "Key architectures: CNN (images), RNN/LSTM (sequences), Transformer (attention). "
        "Frameworks: TensorFlow, PyTorch. Requires large data and GPU compute."
    ),
    "neural network": (
        "Neural Networks: Input Layer receives features, Hidden Layers learn representations, "
        "Output Layer produces predictions. Each neuron: weighted sum then activation function. "
        "Training: forward pass, compute loss, backpropagation, weight update. "
        "Deep networks (many layers) = Deep Learning."
    ),
    "machine learning": (
        "Machine Learning enables systems to learn from data without explicit programming. "
        "Types: Supervised (labelled data), Unsupervised (unlabelled), Reinforcement (rewards). "
        "Steps: Collect data, Preprocess, Choose algorithm, Train, Evaluate, Deploy. "
        "Libraries: scikit-learn, TensorFlow, PyTorch."
    ),
    "artificial intelligence": (
        "Artificial Intelligence simulates human intelligence in machines: reasoning, "
        "learning, problem-solving, perception, and language understanding. "
        "Categories: Narrow AI (current — Siri, AlphaGo), General AI (human-level, "
        "not yet achieved), Super AI (theoretical). Sub-fields: ML, Deep Learning, "
        "NLP, Computer Vision, Robotics. Transforming every industry."
    ),
}
