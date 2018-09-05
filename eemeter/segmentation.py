import pandas as pd
from patsy import dmatrix

__all__ = (
    "iterate_segmented_dataset",
    "segment_time_series",
    "SegmentModel",
    "SegmentedModel",
)


class SegmentModel(object):
    def __init__(self, segment_name, model, formula, model_params, warnings=None):
        self.segment_name = segment_name
        self.model = model
        self.formula = formula
        self.model_params = model_params

        if warnings is None:
            warnings = []
        self.warnings = warnings

    def predict(self, data):
        design_matrix_granular = dmatrix(
            self.formula.split("~", 1)[1], data, return_type="dataframe"
        )

        parameters = pd.Series(self.model_params)
        prediction = design_matrix_granular.dot(parameters).rename(
            columns={0: "predicted_usage"}
        )
        return prediction


class SegmentedModel(object):
    def __init__(
        self,
        segment_models,
        prediction_segment_type,
        prediction_segment_name_mapping=None,
        prediction_feature_processor=None,
        prediction_feature_processor_kwargs=None,
    ):
        self.segment_models = segment_models

        fitted_model_lookup = {
            segment_model.segment_name: segment_model
            for segment_model in segment_models
        }
        if prediction_segment_name_mapping is None:
            self.model_lookup = fitted_model_lookup
        else:
            self.model_lookup = {
                prediction_segment_name: fitted_model_lookup.get(fitted_segment_name)
                for prediction_segment_name, fitted_segment_name in prediction_segment_name_mapping.items()
            }
        self.prediction_segment_type = prediction_segment_type
        self.prediction_segment_name_mapping = prediction_segment_name_mapping
        self.prediction_feature_processor = prediction_feature_processor
        self.prediction_feature_processor_kwargs = prediction_feature_processor_kwargs

    def predict(self, prediction_index, temperature):
        prediction_segmentation = segment_time_series(
            temperature.index, self.prediction_segment_type
        )
        iterator = iterate_segmented_dataset(
            temperature.to_frame("temperature_mean"),
            segmentation=prediction_segmentation,
            feature_processor=self.prediction_feature_processor,
            feature_processor_kwargs=self.prediction_feature_processor_kwargs,
            feature_processor_segment_name_mapping=self.prediction_segment_name_mapping,
        )
        predictions = {}
        for segment_name, segmented_data in iterator:
            segment_model = self.model_lookup.get(segment_name)
            if segment_model is None:
                continue
            prediction = segment_model.predict(segmented_data).reindex(prediction_index)
            predictions[segment_name] = prediction
        predictions = pd.DataFrame(predictions)
        return predictions.sum(axis=1)


def iterate_segmented_dataset(
    data,
    segmentation=None,
    feature_processor=None,
    feature_processor_kwargs=None,
    feature_processor_segment_name_mapping=None,
):

    if feature_processor_kwargs is None:
        feature_processor_kwargs = {}

    if feature_processor_segment_name_mapping is None:
        feature_processor_segment_name_mapping = {}

    def _apply_feature_processor(segment_name, segment_data):
        feature_processor_segment_name = feature_processor_segment_name_mapping.get(
            segment_name, segment_name
        )

        if feature_processor is not None:
            segment_data = feature_processor(
                feature_processor_segment_name, segment_data, **feature_processor_kwargs
            )
        return segment_data

    def _add_weights(data, weights):
        return pd.merge(data, weights, left_index=True, right_index=True)[
            weights.weight > 0
        ]  # take only non zero weights

    if segmentation is None:
        # spoof segment name and weights column
        segment_name = None
        weights = pd.DataFrame({"weight": 1}, index=data.index)
        segment_data = _add_weights(data, weights)
        yield segment_name, _apply_feature_processor(segment_name, segment_data)
    else:
        for segment_name, segment_weights in segmentation.iteritems():
            weights = segment_weights.to_frame("weight")
            segment_data = _add_weights(data, weights)
            yield segment_name, _apply_feature_processor(segment_name, segment_data)


def _get_calendar_year_coverage_warning(index):
    pass


def _get_hourly_coverage_warning(index, min_fraction_daily_coverage=0.9):
    pass
    # warnings = []
    # summary = data.assign(total_days=data.index.days_in_month)
    # summary = summary.groupby(summary.index.month) \
    #     .agg({'meter_value': len, 'model_id': max, 'total_days': max})
    # summary['hourly_coverage'] = summary.meter_value / \
    #     (summary.total_days * 24)
    #
    # for month in baseline_months:
    #     row = summary.loc[summary.index == month]
    #     if (len(row.index) == 0):
    #         warnings.append(EEMeterWarning(
    #             qualified_name=(
    #                 'eemeter.caltrack_hourly.no_baseline_data_for_month'
    #             ),
    #             description=(
    #                 'No data for one of the baseline months. Month {}'
    #                 .format(month)
    #             ),
    #             data={
    #                 'model_id': model_id,
    #                 'month': month,
    #                 'hourly_coverage': 0
    #             }
    #         ))
    #         continue
    #
    #     if (row.hourly_coverage.values[0] < min_fraction_daily_coverage):
    #         warnings.append(EEMeterWarning(
    #             qualified_name=(
    #                 'eemeter.caltrack_hourly.insufficient_hourly_coverage'
    #             ),
    #             description=(
    #                 'Data for this model does not meet the minimum '
    #                 'hourly sufficiency criteria. '
    #                 'Month {}: Coverage: {}'
    #                 .format(month, row.hourly_coverage.values[0])
    #             ),
    #             data={
    #                 'model_id': model_id,
    #                 'month': month,
    #                 'total_days': row.total_days.values[0],
    #                 'hourly_coverage': row.hourly_coverage.values[0]
    #             }
    #         ))
    #
    # return warnings


def segment_time_series(index, segment_type="single"):

    if segment_type == "single":
        segment_weights = pd.DataFrame({"all": 1.0}, index=index)

    elif segment_type == "one_month":
        segment_weights = pd.DataFrame(
            {
                month_name: (index.month == month_number).astype(float)
                for month_name, month_number in [
                    ("jan", 1),
                    ("feb", 2),
                    ("mar", 3),
                    ("apr", 4),
                    ("may", 5),
                    ("jun", 6),
                    ("jul", 7),
                    ("aug", 8),
                    ("sep", 9),
                    ("oct", 10),
                    ("nov", 11),
                    ("dec", 12),
                ]
            },
            index=index,
        )

    elif segment_type == "three_month":
        segment_weights = pd.DataFrame(
            {
                month_names: (index.month.map(lambda i: i in month_numbers)).astype(
                    float
                )
                for month_names, month_numbers in [
                    ("dec-jan-feb", (12, 1, 2)),
                    ("jan-feb-mar", (1, 2, 3)),
                    ("feb-mar-apr", (2, 3, 4)),
                    ("mar-apr-may", (3, 4, 5)),
                    ("apr-may-jun", (4, 5, 6)),
                    ("may-jun-jul", (5, 6, 7)),
                    ("jun-jul-aug", (6, 7, 8)),
                    ("jul-aug-sep", (7, 8, 9)),
                    ("aug-sep-oct", (8, 9, 10)),
                    ("sep-oct-nov", (9, 10, 11)),
                    ("oct-nov-dec", (10, 11, 12)),
                    ("nov-dec-jan", (11, 12, 1)),
                ]
            },
            index=index,
        )

    elif segment_type == "three_month_weighted":
        segment_weights = pd.DataFrame(
            {
                month_names: index.month.map(
                    lambda i: month_weights.get(str(i), 0.0)
                ).astype(float)
                for month_names, month_weights in [
                    ("dec-jan-feb-weighted", {"12": 0.5, "1": 1, "2": 0.5}),
                    ("jan-feb-mar-weighted", {"1": 0.5, "2": 1, "3": 0.5}),
                    ("feb-mar-apr-weighted", {"2": 0.5, "3": 1, "4": 0.5}),
                    ("mar-apr-may-weighted", {"3": 0.5, "4": 1, "5": 0.5}),
                    ("apr-may-jun-weighted", {"4": 0.5, "5": 1, "6": 0.5}),
                    ("may-jun-jul-weighted", {"5": 0.5, "6": 1, "7": 0.5}),
                    ("jun-jul-aug-weighted", {"6": 0.5, "7": 1, "8": 0.5}),
                    ("jul-aug-sep-weighted", {"7": 0.5, "8": 1, "9": 0.5}),
                    ("aug-sep-oct-weighted", {"8": 0.5, "9": 1, "10": 0.5}),
                    ("sep-oct-nov-weighted", {"9": 0.5, "10": 1, "11": 0.5}),
                    ("oct-nov-dec-weighted", {"10": 0.5, "11": 1, "12": 0.5}),
                    ("nov-dec-jan-weighted", {"11": 0.5, "12": 1, "1": 0.5}),
                ]
            },
            index=index,
        )

    else:
        raise ValueError("Invalid segment type: %s" % (segment_type))

    # TODO: Do something with these
    _get_hourly_coverage_warning(segment_weights)  # each model
    _get_calendar_year_coverage_warning(index)  # whole index

    return segment_weights


def fit_segmented_model(
    segmented_dataset_dict,
    fit_segment,
    prediction_segment_type,
    prediction_segment_name_mapping,
    prediction_feature_processor,
    prediction_feature_processor_kwargs,
):
    segment_models = []
    for segment_name, segment_data in segmented_dataset_dict.items():
        segment_model = fit_segment(segment_name, segment_data)
        segment_models.append(segment_model)
    segmented_model = SegmentedModel(
        segment_models,
        prediction_segment_type=prediction_segment_type,
        prediction_segment_name_mapping=prediction_segment_name_mapping,
        prediction_feature_processor=prediction_feature_processor,
        prediction_feature_processor_kwargs=prediction_feature_processor_kwargs,
    )
    return segmented_model