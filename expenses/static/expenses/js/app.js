
(() => {
    // MIDNIGHT EMERALD & AWWWARDS LUXURY FINTECH CHART SYSTEM

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
    const currencySymbol = document.documentElement.dataset.currencySymbol || '₹';
    const currencyLocale = document.documentElement.dataset.currencyLocale || 'en-IN';

    function baseOptions() {
        const isDark = document.documentElement.dataset.theme !== 'light';

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
                duration: 900,
                easing: 'easeOutQuart'
            },

            plugins: {
                legend: {
                    position: 'top',
                    align: 'end',
                    labels: {
                        usePointStyle: true,
                        pointStyle: 'circle',
                        boxWidth: 8,
                        boxHeight: 8,
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
                    backgroundColor: isDark ? 'rgba(20, 24, 23, 0.95)' : 'rgba(255, 255, 255, 0.98)',
                    titleColor: isDark ? '#F5F7F6' : '#0D1411',
                    bodyColor: isDark ? '#929B96' : '#607067',
                    borderColor: isDark ? 'rgba(255, 255, 255, 0.12)' : 'rgba(0, 0, 0, 0.1)',
                    borderWidth: 1,
                    padding: 14,
                    cornerRadius: 12,
                    displayColors: true,
                    boxPadding: 6,
                    callbacks: {
                        label: context =>
                            ` ${context.dataset.label}: ${currencySymbol}${Number(context.raw).toLocaleString(currencyLocale, { minimumFractionDigits: 2 })}`
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
                            currencySymbol + Number(value).toLocaleString(currencyLocale)
                    }
                }
            }
        };
    }

    window.LedgerlyCharts = {

        // MONTHLY CASH FLOW (DUAL BAR WITH MULTI-STOP GRADIENTS)
        cashFlow(id, data) {
            const canvas = document.getElementById(id);

            if (!canvas || !window.Chart) return;

            const ctx = canvas.getContext('2d');

            // Create Canvas Multi-Stop Gradients
            let incomeGradient = '#10B981';
            let expenseGradient = '#FB7185';

            try {
                const ig = ctx.createLinearGradient(0, 0, 0, 240);
                ig.addColorStop(0, '#34D399');
                ig.addColorStop(1, '#059669');
                incomeGradient = ig;

                const eg = ctx.createLinearGradient(0, 0, 0, 240);
                eg.addColorStop(0, '#FDA4AF');
                eg.addColorStop(1, '#E11D48');
                expenseGradient = eg;
            } catch (e) {
                // Fallback to solid colors if context unavailable
            }

            new Chart(canvas, {
                type: 'bar',

                data: {
                    labels: data.labels,

                    datasets: [
                        {
                            label: 'Inflow',
                            data: data.income,
                            backgroundColor: incomeGradient,
                            hoverBackgroundColor: '#34D399',
                            borderRadius: 8,
                            borderSkipped: false,
                            maxBarThickness: 28,
                            categoryPercentage: 0.65,
                            barPercentage: 0.82
                        },

                        {
                            label: 'Outflow',
                            data: data.expenses,
                            backgroundColor: expenseGradient,
                            hoverBackgroundColor: '#FDA4AF',
                            borderRadius: 8,
                            borderSkipped: false,
                            maxBarThickness: 28,
                            categoryPercentage: 0.65,
                            barPercentage: 0.82
                        }
                    ]
                },

                options: baseOptions()
            });
        },

        // SPENDING CATEGORY DOUGHNUT
        category(id, data) {
            const canvas = document.getElementById(id);

            if (!canvas || !window.Chart) return;

            const hasData = data.category_values.length > 0;
            const isDark = document.documentElement.dataset.theme !== 'light';

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
                        borderWidth: 3,
                        hoverOffset: 8,
                        spacing: 2
                    }]
                },

                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '72%',

                    animation: {
                        animateRotate: true,
                        duration: 850
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
                                padding: 14,
                                font: {
                                    family: 'Plus Jakarta Sans',
                                    size: 11,
                                    weight: '600'
                                }
                            }
                        },

                        tooltip: {
                            enabled: hasData,
                            backgroundColor: isDark ? 'rgba(20, 24, 23, 0.95)' : 'rgba(255, 255, 255, 0.98)',
                            titleColor: isDark ? '#F5F7F6' : '#0D1411',
                            bodyColor: isDark ? '#929B96' : '#607067',
                            borderColor: isDark ? 'rgba(255, 255, 255, 0.12)' : 'rgba(0, 0, 0, 0.1)',
                            borderWidth: 1,
                            padding: 12,
                            cornerRadius: 10,
                            callbacks: {
                                label: context =>
                                    ` ${context.label}: ${currencySymbol}${Number(context.raw).toLocaleString(currencyLocale, { minimumFractionDigits: 2 })}`
                            }
                        }
                    }
                }
            });
        }
    };

    // AWWWARDS DYNAMIC RADIAL MOUSE GLOW ON BENTO CARDS
    document.addEventListener('DOMContentLoaded', () => {
        const bentoCards = document.querySelectorAll('.bento-card, .stat-card, .panel');

        bentoCards.forEach(card => {
            card.addEventListener('mousemove', e => {
                const rect = card.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                card.style.setProperty('--mouse-x', `${x}px`);
                card.style.setProperty('--mouse-y', `${y}px`);
            });
        });
    });

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
    const transactionType = document.getElementById('id_transaction_type');
    const category = document.getElementById('id_category');

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
