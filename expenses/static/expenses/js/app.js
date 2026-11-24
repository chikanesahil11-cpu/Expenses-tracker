
(() => {
    // MIDNIGHT EMERALD — CHART COLOUR SYSTEM

    const palette = [
        '#10B981',
        '#34D399',
        '#059669',
        '#6EE7B7',
        '#A7F3D0',
        '#2DD4BF',
        '#14B8A6',
        '#0F766E'
    ];

    const chartText = '#929B96';
    const chartGrid = 'rgba(255, 255, 255, 0.04)';

    function baseOptions() {
        const isDark = document.documentElement.dataset.theme === 'dark';

        const textColor = isDark ? chartText : '#607067';
        const gridColor = isDark ? chartGrid : 'rgba(0, 0, 0, 0.05)';

        return {
            responsive: true,
            maintainAspectRatio: false,

            interaction: {
                intersect: false,
                mode: 'index'
            },

            animation: {
                duration: 750,
                easing: 'easeOutQuart'
            },

            plugins: {
                legend: {
                    position: 'top',
                    align: 'end',
                    labels: {
                        usePointStyle: true,
                        pointStyle: 'circle',
                        boxWidth: 7,
                        boxHeight: 7,
                        padding: 16,
                        color: textColor,
                        font: {
                            family: 'Plus Jakarta Sans',
                            size: 11,
                            weight: '600'
                        }
                    }
                },

                tooltip: {
                    backgroundColor: isDark ? '#141817' : '#ffffff',
                    titleColor: isDark ? '#F5F7F6' : '#0D1411',
                    bodyColor: isDark ? '#929B96' : '#607067',
                    borderColor: isDark ? '#252B28' : '#E2E8E5',
                    borderWidth: 1,
                    padding: 12,
                    cornerRadius: 8,
                    displayColors: true,
                    callbacks: {
                        label: context =>
                            `${context.dataset.label}: ₹${Number(context.raw).toLocaleString('en-IN')}`
                    }
                }
            },

            scales: {
                x: {
                    grid: {
                        display: false
                    },
                    border: {
                        display: false
                    },
                    ticks: {
                        color: textColor,
                        font: {
                            family: 'Plus Jakarta Sans',
                            size: 11,
                            weight: '500'
                        }
                    }
                },

                y: {
                    beginAtZero: true,
                    grid: {
                        color: gridColor,
                        drawTicks: false
                    },
                    border: {
                        display: false
                    },
                    ticks: {
                        color: textColor,
                        padding: 10,
                        font: {
                            family: 'Plus Jakarta Sans',
                            size: 11,
                            weight: '500'
                        },
                        callback: value =>
                            '₹' + Number(value).toLocaleString('en-IN')
                    }
                }
            }
        };
    }

    window.LedgerlyCharts = {

        // MONTHLY CASH FLOW
        cashFlow(id, data) {
            const canvas = document.getElementById(id);

            if (!canvas || !window.Chart) return;

            new Chart(canvas, {
                type: 'bar',

                data: {
                    labels: data.labels,

                    datasets: [
                        {
                            label: 'Income',
                            data: data.income,
                            backgroundColor: '#10b981',
                            hoverBackgroundColor: '#34d399',
                            borderRadius: 7,
                            borderSkipped: false,
                            maxBarThickness: 25,
                            categoryPercentage: 0.65,
                            barPercentage: 0.8
                        },

                        {
                            label: 'Expenses',
                            data: data.expenses,
                            backgroundColor: '#fb7185',
                            hoverBackgroundColor: '#fda4af',
                            borderRadius: 7,
                            borderSkipped: false,
                            maxBarThickness: 25,
                            categoryPercentage: 0.65,
                            barPercentage: 0.8
                        }
                    ]
                },

                options: baseOptions()
            });
        },

        // SPENDING CATEGORY
        category(id, data) {
            const canvas = document.getElementById(id);

            if (!canvas || !window.Chart) return;

            const hasData = data.category_values.length > 0;

            const isDark =
                document.documentElement.dataset.theme === 'dark';

            new Chart(canvas, {
                type: 'doughnut',

                data: {
                    labels: hasData
                        ? data.category_labels
                        : ['No expense data'],

                    datasets: [{
                        data: hasData
                            ? data.category_values
                            : [1],

                        backgroundColor: hasData
                            ? palette
                            : [isDark ? '#1B211E' : '#E2E8E5'],

                        borderColor: isDark ? '#141817' : '#ffffff',
                        borderWidth: 2,
                        hoverOffset: 6,
                        spacing: 3
                    }]
                },

                options: {
                    responsive: true,
                    maintainAspectRatio: false,

                    cutout: '75%',

                    animation: {
                        animateRotate: true,
                        duration: 800
                    },

                    plugins: {
                        legend: {
                            position: 'bottom',

                            labels: {
                                usePointStyle: true,
                                pointStyle: 'circle',
                                boxWidth: 7,
                                boxHeight: 7,
                                color: isDark ? chartText : '#607067',
                                padding: 16,

                                font: {
                                    family: 'Plus Jakarta Sans',
                                    size: 11,
                                    weight: '600'
                                }
                            }
                        },

                        tooltip: {
                            enabled: hasData,

                            backgroundColor: isDark
                                ? '#141817'
                                : '#ffffff',

                            titleColor: isDark
                                ? '#F5F7F6'
                                : '#0D1411',

                            bodyColor: isDark
                                ? '#929B96'
                                : '#607067',

                            borderColor: isDark
                                ? '#252B28'
                                : '#E2E8E5',

                            borderWidth: 1,
                            padding: 12,
                            cornerRadius: 8,

                            callbacks: {
                                label: context =>
                                    `${context.label}: ₹${Number(context.raw).toLocaleString('en-IN')}`
                            }
                        }
                    }
                }
            });
        }
    };

    // MOBILE SIDEBAR
    const menuButton = document.querySelector('.menu-toggle');
    const sidebar = document.getElementById('sidebar');

    if (menuButton && sidebar) {
        menuButton.addEventListener('click', () => {
            sidebar.classList.toggle('is-open');
        });
    }

    // DELETE CONFIRMATION
    document.querySelectorAll('[data-confirm]').forEach(button => {
        button.addEventListener('click', event => {
            if (!window.confirm(button.dataset.confirm)) {
                event.preventDefault();
            }
        });
    });

    // TRANSACTION CATEGORY FILTER
    const transactionType =
        document.getElementById('id_transaction_type');

    const category =
        document.getElementById('id_category');

    if (transactionType && category) {

        const filterCategories = () => {
            const selectedType = transactionType.value;
            let hasValidSelection = false;

            Array.from(category.options).forEach(option => {
                if (!option.value) return;

                const show = option.dataset.type === selectedType;

                option.hidden = !show;
                option.disabled = !show;

                if (option.selected && show) {
                    hasValidSelection = true;
                }
            });

            if (!hasValidSelection) {
                category.value = '';
            }
        };

        transactionType.addEventListener('change', filterCategories);
        filterCategories();
    }

})();
