
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    path('register/', views.register, name='register'),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    path('categories/', views.category_list, name='category_list'),

    path('transactions/', views.transaction_list, name='transaction_list'),
    path('transactions/add/', views.transaction_create, name='transaction_create'),
    path('transactions/<int:pk>/', views.transaction_detail, name='transaction_detail'),
    path('transactions/<int:pk>/edit/', views.transaction_update, name='transaction_update'),
    path('transactions/<int:pk>/duplicate/', views.transaction_duplicate, name='transaction_duplicate'),
    path('transactions/<int:pk>/delete/', views.transaction_delete, name='transaction_delete'),
    path('transactions/import/', views.transaction_import_csv, name='transaction_import_csv'),
    path('transactions/export/', views.transaction_export_csv, name='transaction_export_csv'),

    path('budgets/', views.budget_list, name='budget_list'),
    path('budgets/add/', views.budget_create, name='budget_create'),
    path('budgets/<int:pk>/edit/', views.budget_update, name='budget_update'),
    path('budgets/<int:pk>/delete/', views.budget_delete, name='budget_delete'),

    path('goals/', views.goal_list, name='goal_list'),
    path('goals/add/', views.goal_create, name='goal_create'),
    path('goals/<int:pk>/edit/', views.goal_update, name='goal_update'),
    path('goals/<int:pk>/deposit/', views.goal_deposit, name='goal_deposit'),
    path('goals/<int:pk>/delete/', views.goal_delete, name='goal_delete'),

    path('recurring/', views.recurring_list, name='recurring_list'),
    path('recurring/add/', views.recurring_create, name='recurring_create'),
    path('recurring/<int:pk>/edit/', views.recurring_update, name='recurring_update'),
    path('recurring/<int:pk>/toggle/', views.recurring_toggle, name='recurring_toggle'),
    path('recurring/<int:pk>/delete/', views.recurring_delete, name='recurring_delete'),
    path('recurring/generate/', views.recurring_run, name='recurring_run'),

    path('reports/', views.reports, name='reports'),
    path('reports/download/', views.financial_report_pdf, name='financial_report_pdf'),

    path('calendar/', views.transaction_calendar, name='transaction_calendar'),
    path('accounts/', views.account_list, name='account_list'),
    path('accounts/add/', views.account_create, name='account_create'),
    path('accounts/<int:pk>/edit/', views.account_update, name='account_update'),
    path('accounts/<int:pk>/delete/', views.account_delete, name='account_delete'),
    path('settings/', views.settings_view, name='settings_view'),
    path('settings/export/json/', views.data_export_json, name='data_export_json'),
    path('settings/account/delete/', views.account_delete_user, name='account_delete_user'),
]
    