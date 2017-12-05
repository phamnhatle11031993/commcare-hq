/* globals d3, nv */
hqDefine("reports/js/aggregate_app_status", function() {
    function setupCharts(data, div) {
        nv.addGraph(function() {
            var chart = nv.models.multiBarChart()
              .transitionDuration(100)
              .showControls(false)
              .reduceXTicks(true)
              .rotateLabels(0)
              .groupSpacing(0.1)
            ;

            chart.yAxis
                .tickFormat(d3.format(',f'));

            d3.select('#' + div + ' svg')
                .datum([data])
                .call(chart);

            nv.utils.windowResize(chart.update);
            return chart;
        });
    }
    $(document).ajaxSuccess(function(event, xhr, settings) {
        if (settings.url.match(/reports\/async\/aggregate_user_status/)) {
            setupCharts($("#submission-percentages").data("value"), 'submission_chart');
            setupCharts($("#sync-percentages").data("value"), 'sync_chart');
            $('.chart-toggle').click(function () {
                $(this).parent().children().not(this).removeClass('btn-primary');  // deselect other buttons
                $(this).addClass('btn-primary');  // select self
                // update data
                setupCharts($("#" + $(this).data('chart-data')).data("value"), $(this).data('chart-div'));
            });
        }
    });
});