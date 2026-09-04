#include <pluginlib/class_list_macros.h>
#include <QHBoxLayout>
#include <QVBoxLayout>
#include <QFileDialog>
#include <QMainWindow>
#include <QFileInfo>
#include <QMessageBox>
#include <QProcess>
#include <QDateTime>
#include <QSignalBlocker>
#include <QTextStream>
#include <QFontDatabase>
#include <QHeaderView>
#include <QScrollArea>
#include <QDockWidget>
#include <QToolBar>
#include <QMenuBar>
#include <QStatusBar>
#include "my_rviz_plugin/my_rviz_plugin.h"
#include <boost/date_time/posix_time/posix_time.hpp>
#include <ros/package.h>
#include <ros/message_operations.h>

#include <QDir>
#include <QTimer>
#include <set>
#include <array>
#include <limits>
#include <cmath>
#include <algorithm>
#include <sstream>
#include <iomanip>
#include <map>

namespace my_rviz_plugin
{

namespace
{
const char* kPublicCanRearTopic = "/rear/signals";
const char* kPublicCanFrontTopic = "/front/signals";
const char* kManualTestTagTopicDisplay = "/arbe/settings/manual_test_tag";

// Queue a refresh for the controls inside the player panel only.  Do not
// repaint the RViz top-level window or any parent of content_widget: doing so
// can resize/recreate OGRE's native OpenGL surface in a remote X11/XRDP
// session, which may produce a white window or a driver crash.
void queuePanelControlRefresh(QWidget* content_widget)
{
  if (!content_widget)
  {
    return;
  }

  QTimer::singleShot(0, content_widget, [content_widget]() {
    if (QLayout* content_layout = content_widget->layout())
    {
      content_layout->invalidate();
      content_layout->activate();
    }

    // Repaint concrete controls rather than the QMainWindow.  QTextEdit and
    // other compound widgets have child viewports, so findChildren() is
    // intentionally recursive.
    const auto controls = content_widget->findChildren<QWidget*>();
    for (QWidget* control : controls)
    {
      if (control && control->isVisible())
      {
        control->update();
        control->repaint();
      }
    }

    content_widget->update();
    content_widget->repaint();
  });
}

QString publicCanSignalGroupTitle(const QString& field_name)
{
  if (!field_name.startsWith("m_") || field_name.size() < 6)
  {
    return QString();
  }

  const QString id = field_name.mid(2, 3).toUpper();
  bool ok = false;
  id.toInt(&ok, 16);
  if (!ok)
  {
    return QString();
  }
  return "CAN ID 0x" + id;
}

void addTreeChild(QTreeWidgetItem* parent, const QString& name, const QString& value)
{
  QTreeWidgetItem* child = new QTreeWidgetItem(parent);
  child->setText(0, name.trimmed());
  child->setText(1, value.trimmed());
}

void addArrayChildren(QTreeWidgetItem* parent, const QString& values_text)
{
  QString trimmed = values_text.trimmed();
  if (trimmed.startsWith("[") && trimmed.endsWith("]"))
  {
    trimmed = trimmed.mid(1, trimmed.size() - 2);
  }

  const QStringList values = trimmed.split(",", QString::SkipEmptyParts);
  for (int i = 0; i < values.size(); ++i)
  {
    addTreeChild(parent, QString("[%1]").arg(i), values.at(i));
  }
}

void collectExpandedTopLevelItems(QTreeWidget* tree_widget, std::set<QString>& expanded_items)
{
  if (!tree_widget)
  {
    return;
  }

  for (int i = 0; i < tree_widget->topLevelItemCount(); ++i)
  {
    QTreeWidgetItem* item = tree_widget->topLevelItem(i);
    if (item && item->isExpanded())
    {
      expanded_items.insert(item->text(0));
    }
  }
}

const char* adasWarningName(int bit_index)
{
  static const char* kNames[15] = {
    "BSD_L", "BSD_R",
    "LCA_L", "LCA_R",
    "DOW_L", "DOW_R",
    "RCW",
    "RCTA_L", "RCTA_R",
    "RCTB_L", "RCTB_R",
    "FCTA_L", "FCTA_R",
    "FCTB_L", "FCTB_R",
  };

  if (bit_index < 0 || bit_index >= 15)
  {
    return "UNKNOWN";
  }
  return kNames[bit_index];
}

QString activeAdasWarnings(const std::array<int, 15>& bits)
{
  QStringList active;
  for (int i = 0; i < 15; ++i)
  {
    if (bits[static_cast<size_t>(i)] > 0)
    {
      active << QString("%1=%2").arg(adasWarningName(i)).arg(bits[static_cast<size_t>(i)]);
    }
  }
  return active.isEmpty() ? "NONE" : active.join("|");
}

template <typename MsgT>
QString formatPublicCanMessageImpl(const MsgT& msg,
                                   const QString& topic,
                                   int msg_index,
                                   const ros::Time& bag_time)
{
  size_t valid_count = 0;
  for (size_t i = 0; i < msg.signal_valid.size(); ++i)
  {
    if (msg.signal_valid[i] != 0)
    {
      ++valid_count;
    }
  }

  std::ostringstream ss;
  ss << "topic: " << topic.toStdString() << "\n";
  ss << "bag_msg_index: " << msg_index << "\n";
  ss << "bag_time: " << std::fixed << std::setprecision(6) << bag_time.toSec() << "\n";
  ss << "msg_stamp: " << msg.header.stamp.toSec() << "\n";
  ss << "frame_id: " << msg.header.frame_id << "\n";
  ss << "channel: " << static_cast<int>(msg.channel) << "\n";
  ss << "received_frame_count: " << msg.received_frame_count << "\n";
  ss << "decoded_frame_count: " << msg.decoded_frame_count << "\n";
  ss << "valid_signals: " << valid_count << "/" << msg.signal_valid.size() << "\n";
  ss << "----------------------------------------\n";
  ss << "signal_valid_flat: [";
  for (size_t i = 0; i < msg.signal_valid.size(); ++i)
  {
    if (i != 0)
    {
      ss << ", ";
    }
    ss << static_cast<int>(msg.signal_valid[i]);
  }
  ss << "]\n";
  ss << "signal_age_ms_flat: [";
  for (size_t i = 0; i < msg.signal_age_ms.size(); ++i)
  {
    if (i != 0)
    {
      ss << ", ";
    }
    ss << std::fixed << std::setprecision(3) << msg.signal_age_ms[i];
  }
  ss << "]\n";
  ros::message_operations::Printer<MsgT>::stream(ss, "", msg);
  return QString::fromStdString(ss.str());
}

template <typename MsgT>
QString formatXcpMessageImpl(const MsgT& msg,
                             const QString& topic,
                             int msg_index,
                             const ros::Time& bag_time)
{
  std::ostringstream ss;
  ss << "topic: " << topic.toStdString() << "\n";
  ss << "bag_msg_index: " << msg_index << "\n";
  ss << "bag_time: " << std::fixed << std::setprecision(6) << bag_time.toSec() << "\n";
  ss << "msg_stamp: " << msg.header.stamp.toSec() << "\n";
  ss << "frame_id: " << msg.header.frame_id << "\n";
  ss << "----------------------------------------\n";
  ros::message_operations::Printer<MsgT>::stream(ss, "", msg);
  return QString::fromStdString(ss.str());
}

QString formatLguFrameIdLabel(int main_frame_index,
                              int main_radar_index,
                              const std::array<int, 5>& lgu_frame_ids,
                              const std::array<double, 5>& lgu_stamp_secs,
                              const QString& main_bag_time_text,
                              const QString& main_bag_time_ros_sec_text,
                              const QString& main_lgu_time_text,
                              const QString& main_lgu_time_ros_sec_text)
{
  auto radar_frame_text = [&lgu_frame_ids](int radar_id) {
    if (radar_id < 0 || radar_id >= static_cast<int>(lgu_frame_ids.size()) || lgu_frame_ids[radar_id] < 0)
    {
      return QString("N/A");
    }
    return QString::number(lgu_frame_ids[radar_id]);
  };

  auto radar_ros_time_text = [&lgu_stamp_secs](int radar_id) {
    if (radar_id < 0 || radar_id >= static_cast<int>(lgu_stamp_secs.size()) || lgu_stamp_secs[radar_id] <= 0.0)
    {
      return QString("N/A");
    }
    return QString::number(lgu_stamp_secs[radar_id], 'f', 6);
  };

  auto radar_local_time_text = [&lgu_stamp_secs](int radar_id) {
    if (radar_id < 0 || radar_id >= static_cast<int>(lgu_stamp_secs.size()) || lgu_stamp_secs[radar_id] <= 0.0)
    {
      return QString("N/A");
    }

    ros::Time stamp;
    stamp.fromSec(lgu_stamp_secs[radar_id]);
    boost::posix_time::ptime local_time = stamp.toBoost() + boost::posix_time::hours(8);
    return QString::fromStdString(boost::posix_time::to_simple_string(local_time));
  };

  return QString("LGU Event Index: %1  Active Radar: %2  EventBagTime(CN): %3  EventBagRosSec: %4\n"
                 "ActiveLGUTime(CN): %5  ActiveLGURosSec: %6\n"
                 "LGU FrameID -> R1:%7  R2:%8  R3:%9  R4:%10\n"
                 "LGU RosSec  -> R1:%11  R2:%12  R3:%13  R4:%14\n"
                 "LGU Local   -> R1:%15  R2:%16  R3:%17  R4:%18")
      .arg(main_frame_index >= 0 ? QString::number(main_frame_index) : QString("N/A"))
      .arg(main_radar_index)
      .arg(main_bag_time_text)
      .arg(main_bag_time_ros_sec_text)
      .arg(main_lgu_time_text)
      .arg(main_lgu_time_ros_sec_text)
      .arg(radar_frame_text(1))
      .arg(radar_frame_text(2))
      .arg(radar_frame_text(3))
      .arg(radar_frame_text(4))
      .arg(radar_ros_time_text(1))
      .arg(radar_ros_time_text(2))
      .arg(radar_ros_time_text(3))
      .arg(radar_ros_time_text(4))
      .arg(radar_local_time_text(1))
      .arg(radar_local_time_text(2))
      .arg(radar_local_time_text(3))
      .arg(radar_local_time_text(4));
}
}

MyRvizPlugin::MyRvizPlugin(QWidget* parent)
  : rviz::Panel(parent), bag_reader_(new BagReader()), 
  frame_count0(0), 
  frame_count1(0),  frame_count2(0), 
  frame_count3(0), frame_count4(0),
  mainRadarIndex_(3), current_bag_index_(-1), folder_mode_(false), kpi_batch_running_(false), internal_stop_request_(false), kpi_batch_timeout_handling_(false), current_loaded_bag_path_(""), public_can_ch3_dialog_(nullptr), public_can_ch2_dialog_(nullptr), xcp_front_dialog_(nullptr), xcp_rear_dialog_(nullptr), public_can_ch3_tree_(nullptr), public_can_ch2_tree_(nullptr), xcp_front_text_(nullptr), xcp_rear_text_(nullptr), public_can_ch3_last_msg_index_(-1), public_can_ch2_last_msg_index_(-1), public_can_ch3_has_msg_(false), public_can_ch2_has_msg_(false), kpi_output_dir_(""), kpi_batch_script_path_(""), kpi_batch_watchdog_timer_(nullptr), kpi_batch_playback_timeout_ms_(180000), kpi_respect_bag_timing_(true), last_main_radar_stamp_sec_(0.0), pending_service_radar_id_(-1), pending_service_frame_id_(-1), scene_dispatch_active_(false), use_warning_status_with_frame_(true), kpi_pair_mode_active_(true)
{
  for (auto& pending_frames : pending_event_frame_ids_)
  {
    pending_frames.clear();
  }
  pending_scene_frame_ids_.fill(-1);
  pending_scene_completed_.fill(false);
  nh_ = ros::NodeHandle();
  ros::param::param<int>("/kpi/batch_frame_timeout_ms", kpi_batch_playback_timeout_ms_, 180000);
  ros::param::param<bool>("/kpi/respect_bag_timing", kpi_respect_bag_timing_, true);
  ros::param::param<bool>("/kpi/use_warning_status_with_frame", use_warning_status_with_frame_, true);
  if (kpi_batch_playback_timeout_ms_ < 1000)
  {
    kpi_batch_playback_timeout_ms_ = 1000;
  }
  kpi_batch_watchdog_timer_ = new QTimer(this);
  kpi_batch_watchdog_timer_->setSingleShot(true);
  connect(kpi_batch_watchdog_timer_, &QTimer::timeout, this, [this]() {
    handleKpiBatchPlaybackTimeout();
  });

  pointcloud_pub0_ = nh_.advertise<arbe_msgs_rvizbag::wfAutosarData>("/wf/corner_radar/lgu_data_0", 10);
  pointcloud_pub1_ = nh_.advertise<arbe_msgs_rvizbag::wfAutosarData>("/wf/corner_radar/lgu_data_1", 10);
  pointcloud_pub2_ = nh_.advertise<arbe_msgs_rvizbag::wfAutosarData>("/wf/corner_radar/lgu_data_2", 10);
  pointcloud_pub3_ = nh_.advertise<arbe_msgs_rvizbag::wfAutosarData>("/wf/corner_radar/lgu_data_3", 10);
  pointcloud_pub4_ = nh_.advertise<arbe_msgs_rvizbag::wfAutosarData>("/wf/corner_radar/lgu_data_4", 10);
  pointcloud_pub5_ = nh_.advertise<arbe_msgs_rvizbag::wfAutosarData>("/wf/corner_radar/lgu_data_5", 10);

  camera_pub0_ = nh_.advertise<sensor_msgs::CompressedImage>("/cv_camera_0/image_raw/compressed", 10);  
  camera_pub1_ = nh_.advertise<sensor_msgs::CompressedImage>("/cv_camera_1/image_raw/compressed", 10);
  camera_pub2_ = nh_.advertise<sensor_msgs::CompressedImage>("/cv_camera_2/image_raw/compressed", 10);
  camera_pub3_ = nh_.advertise<sensor_msgs::CompressedImage>("/cv_camera_3/image_raw/compressed", 10);
  camera_pub4_ = nh_.advertise<sensor_msgs::CompressedImage>("/cv_camera_4/image_raw/compressed", 10);
  camera_pub5_ = nh_.advertise<sensor_msgs::CompressedImage>("/cv_camera_5/image_raw/compressed", 10);
  camera_pub6_ = nh_.advertise<sensor_msgs::CompressedImage>("/cv_camera_6/image_raw/compressed", 10);
  ego_car_info_front_left_pub_ = nh_.advertise<common_xcp_info_publisher_rvizbag::XcpEgoInfo>("/wf/ego_car_info/front_left/parsed", 10);
  ego_car_info_front_right_pub_ = nh_.advertise<common_xcp_info_publisher_rvizbag::XcpEgoInfo>("/wf/ego_car_info/front_right/parsed", 10);
  ego_car_info_rear_left_pub_ = nh_.advertise<common_xcp_info_publisher_rvizbag::XcpEgoInfo>("/wf/ego_car_info/rear_left/parsed", 10);
  ego_car_info_rear_right_pub_ = nh_.advertise<common_xcp_info_publisher_rvizbag::XcpEgoInfo>("/wf/ego_car_info/rear_right/parsed", 10);

  
  car_pub_ = nh_.advertise<arbe_msgs_rvizbag::VehStatusOutput>("/wf/car_id6/parsed2", 1);
  warning_pub_ = nh_.advertise<std_msgs::UInt8MultiArray>("/corner_radar/warning_status_raw", 10);
  public_can_ch3_pub_ = nh_.advertise<common_can_signal_publisher_rvizbag::PublicCanRearSignals>(kPublicCanRearTopic, 10);
  public_can_ch2_pub_ = nh_.advertise<common_can_signal_publisher_rvizbag::PublicCanFrontSignals>(kPublicCanFrontTopic, 10);
  algo_warning_sub_ = nh_.subscribe("/corner_radar/warning_status", 200, &MyRvizPlugin::onAlgoWarningForKpi, this);
  algo_warning_with_frame_sub_ = nh_.subscribe("/corner_radar/warning_status_with_frame", 200, &MyRvizPlugin::onAlgoWarningWithFrameForKpi, this);

  last_lgu_stamp_sec_.fill(0.0);
  last_lgu_frame_id_.fill(-1);
  for (auto& stamps_by_frame : lgu_stamp_by_frame_)
  {
    stamps_by_frame.clear();
  }
  last_main_frame_id_ = -1;

   // 创建异步 spinner，并指定使用 1 个线程
  spinner_ = new ros::AsyncSpinner(1);  // 可以根据需要指定更多的线程
  spinner_->start();
  
  // 创建一个服务并注册回调函数
  service0_ = nh_.advertiseService("/play_single_frame_0", &MyRvizPlugin::handleServiceRequest, this);
  service1_ = nh_.advertiseService("/play_single_frame_1", &MyRvizPlugin::handleServiceRequest, this);
  service2_ = nh_.advertiseService("/play_single_frame_2", &MyRvizPlugin::handleServiceRequest, this);
  service3_ = nh_.advertiseService("/play_single_frame_3", &MyRvizPlugin::handleServiceRequest, this);
  service4_ = nh_.advertiseService("/play_single_frame_4", &MyRvizPlugin::handleServiceRequest, this);

  folder_path_ = new QLineEdit;
  gt_csv_folder_path_ = new QLineEdit;
  select_folder_button_ = new QPushButton("Select Folder");
  select_gt_csv_folder_button_ = new QPushButton("Select GT CSV Folder");
  start_kpi_batch_button_ = new QPushButton("Start KPI Batch");
  current_bag_label_ = new QLabel("Current Bag: N/A");
  current_csv_label_ = new QLabel("Matched CSV: N/A");
  public_can_ch3_button_ = new QPushButton("Public CAN Rear");
  public_can_ch2_button_ = new QPushButton("Public CAN Front");
  xcp_front_button_ = new QPushButton("XCP Front");
  xcp_rear_button_ = new QPushButton("XCP Rear");
  bag_file_path_ = new QLineEdit;
  select_button_ = new QPushButton("Select");
  read_button_ = new QPushButton("Read");
  play_button_ = new QPushButton("Play");
  stop_button_ = new QPushButton("Stop");
  step_forward_button_ = new QPushButton("step->");
  step_backward_button_ = new QPushButton("<-step");
  frame_spinner_ = new QSpinBox;
  step_spinner_ = new QSpinBox;
  frame_count_label_ = new QLabel("Frame Count: Radar(1-LT) 0;Radar(2-RT) 0;Radar(3-LB) 0;Radar(4-RB) 0");
  frame_id_label_ = new QLabel("LGU Event Index: N/A  Active Radar: N/A  EventBagTime(CN): N/A  EventBagRosSec: N/A\nActiveLGUTime(CN): N/A  ActiveLGURosSec: N/A\nLGU FrameID -> R1:N/A  R2:N/A  R3:N/A  R4:N/A\nLGU RosSec  -> R1:N/A  R2:N/A  R3:N/A  R4:N/A\nLGU Local   -> R1:N/A  R2:N/A  R3:N/A  R4:N/A");
  frame_id_label_->setWordWrap(true);
  publish_warning_raw_checkbox_ = new QCheckBox("Publish Warning Raw");
  kpi_pair_mode_checkbox_ = new QCheckBox("KPI Batch Mode (bag+csv pair)");
  scene_mode_checkbox_ = new QCheckBox("Scene Mode (Single Bag Debug)");
  scene_mode_checkbox_->setToolTip("Group nearby radar frames for single-bag debugging. KPI batch always uses strict event mode.");
  scene_mode_checkbox_->setChecked(true);
  kpi_pair_mode_checkbox_->setChecked(false);
  publish_warning_raw_checkbox_->setChecked(true);
  warning_topic_label_ = new QLabel("Warning Topic: N/A");
  warning_summary_text_ = new QTextEdit;
  warning_summary_text_->setReadOnly(true);
  warning_summary_text_->setPlaceholderText("Read a bag to show warning trigger intervals.");
  warning_summary_text_->setMinimumHeight(140);
  warning_summary_text_->setStyleSheet("QTextEdit { color: #000000; background: #ffffff; }");
  manual_tag_topic_label_ = new QLabel("Manual Tag Topic: N/A");
  manual_tag_summary_text_ = new QTextEdit;
  manual_tag_summary_text_->setReadOnly(true);
  manual_tag_summary_text_->setPlaceholderText("Read a bag to show manual test tag messages.");
  manual_tag_summary_text_->setMinimumHeight(160);
  manual_tag_summary_text_->setStyleSheet("QTextEdit { color: #000000; background: #f8fbff; border: 1px solid #7aa7d9; }");
  play_rate_combo_ = new QComboBox;
  select_main_radar_ = new QComboBox;
  frame_slider_ = new QSlider(Qt::Horizontal);
  progress_bar_ = new QProgressBar();

  play_rate_combo_->addItem("1.0");
  play_rate_combo_->addItem("0.25");
  play_rate_combo_->addItem("0.5");
  play_rate_combo_->addItem("1.25");
  play_rate_combo_->addItem("1.5");
  play_rate_combo_->addItem("2.0");

  select_button_->setFixedSize(50, 30);
  read_button_->setFixedSize(50, 30);
  play_button_->setFixedSize(40, 30);
  stop_button_->setFixedSize(40, 30);
  step_forward_button_->setFixedSize(50, 30);
  step_backward_button_->setFixedSize(50, 30);
  select_folder_button_->setFixedSize(100, 30);
  select_gt_csv_folder_button_->setFixedSize(140, 30);
  start_kpi_batch_button_->setFixedSize(120, 30);
  public_can_ch3_button_->setFixedSize(120, 30);
  public_can_ch2_button_->setFixedSize(120, 30);
  xcp_front_button_->setFixedSize(100, 30);
  xcp_rear_button_->setFixedSize(100, 30);

  select_main_radar_->addItem("前雷达(0)");
  select_main_radar_->addItem("前左角(1)");
  select_main_radar_->addItem("前右角(2)");
  select_main_radar_->addItem("后左角(3)");
  select_main_radar_->addItem("后右角(4)");

  frame_spinner_->setMinimum(0);
  step_spinner_->setMinimum(1);
  step_spinner_->setValue(1);

  frame_slider_->setMinimum(0);

  progress_bar_->setRange(0.0,1.2);
  progress_bar_->setValue(0.0);

  QVBoxLayout* layout = new QVBoxLayout;
  QHBoxLayout* file_layout = new QHBoxLayout;
  file_layout->addWidget(bag_file_path_);
  file_layout->addWidget(select_button_);
  file_layout->addWidget(read_button_);
  file_layout->addWidget(select_folder_button_);
  file_layout->addWidget(select_gt_csv_folder_button_);
  file_layout->addWidget(start_kpi_batch_button_);

  QHBoxLayout* layoutnubmber = new QHBoxLayout;
  layoutnubmber->addWidget(frame_spinner_);
  layoutnubmber->addWidget(frame_slider_);

  QHBoxLayout* control_layout = new QHBoxLayout;
  // control_layout->addWidget(new QLabel("Step:"));
  // control_layout->addWidget(step_spinner_);
  control_layout->addWidget(step_backward_button_);
  control_layout->addWidget(step_forward_button_);
  control_layout->addWidget(play_button_);
  control_layout->addWidget(stop_button_);
  control_layout->addWidget(new QLabel("Play Rate:"));
  control_layout->addWidget(play_rate_combo_);
  control_layout->addWidget(select_main_radar_);
  control_layout->addWidget(publish_warning_raw_checkbox_);
  control_layout->addWidget(scene_mode_checkbox_);
  control_layout->addWidget(kpi_pair_mode_checkbox_);
  control_layout->addWidget(public_can_ch3_button_);
  control_layout->addWidget(public_can_ch2_button_);
  control_layout->addWidget(xcp_front_button_);
  control_layout->addWidget(xcp_rear_button_);

  layout->addLayout(file_layout);
  layout->addWidget(frame_count_label_);

  layout->addWidget(folder_path_);
  layout->addWidget(gt_csv_folder_path_);
  layout->addWidget(current_bag_label_);
  layout->addWidget(current_csv_label_);
  layout->addWidget(frame_id_label_);
  layout->addWidget(warning_topic_label_);
  layout->addWidget(warning_summary_text_);
  layout->addWidget(new QLabel("----- Manual Test Tag Separator -----"));
  layout->addWidget(manual_tag_topic_label_);
  layout->addWidget(manual_tag_summary_text_);
  layout->addLayout(layoutnubmber);
  layout->addLayout(control_layout);
  layout->addWidget(progress_bar_);

  // Wrap all content in a QScrollArea so the panel can be shrunk below the
  // contents' natural size; scrollbars appear when widgets do not fit.
  QWidget* content_widget = new QWidget;
  content_widget->setLayout(layout);
  content_widget_ = content_widget;

  QScrollArea* scroll_area = new QScrollArea;
  scroll_area->setWidgetResizable(true);
  scroll_area->setFrameShape(QFrame::NoFrame);
  scroll_area->setHorizontalScrollBarPolicy(Qt::ScrollBarAsNeeded);
  scroll_area->setVerticalScrollBarPolicy(Qt::ScrollBarAsNeeded);
  scroll_area->setWidget(content_widget);

  QVBoxLayout* outer_layout = new QVBoxLayout;
  outer_layout->setContentsMargins(0, 0, 0, 0);
  outer_layout->addWidget(scroll_area);
  setLayout(outer_layout);
  setMinimumSize(50, 50);

  connect(select_button_, SIGNAL(clicked()), this, SLOT(selectBagFile()));
  connect(read_button_, SIGNAL(clicked()), this, SLOT(readBagFile()));
  connect(play_button_, SIGNAL(clicked()), this, SLOT(playBag()));
  connect(stop_button_, SIGNAL(clicked()), this, SLOT(stopBag()));
  connect(frame_spinner_, SIGNAL(valueChanged(int)), this, SLOT(jumpToFrame()));
  connect(step_forward_button_, SIGNAL(clicked()), this, SLOT(stepForward()));
  connect(step_backward_button_, SIGNAL(clicked()), this, SLOT(stepBackward()));
  connect(play_rate_combo_, SIGNAL(currentIndexChanged(int)), this, SLOT(updatePlayRate()));
  connect(frame_slider_, SIGNAL(valueChanged(int)), this, SLOT(sliderValueChanged(int)));
  connect(select_main_radar_, SIGNAL(currentIndexChanged(int)), this, SLOT(selectMainRadar()));
  connect(scene_mode_checkbox_, SIGNAL(toggled(bool)), this, SLOT(sceneModeChanged(bool)));
  connect(select_folder_button_, SIGNAL(clicked()), this, SLOT(selectFolder()));
  connect(select_gt_csv_folder_button_, SIGNAL(clicked()), this, SLOT(selectGtCsvFolder()));
  connect(start_kpi_batch_button_, SIGNAL(clicked()), this, SLOT(startKpiBatch()));
  connect(public_can_ch3_button_, SIGNAL(clicked()), this, SLOT(showPublicCanCh3Window()));
  connect(public_can_ch2_button_, SIGNAL(clicked()), this, SLOT(showPublicCanCh2Window()));
  connect(xcp_front_button_, SIGNAL(clicked()), this, SLOT(showXcpFrontWindow()));
  connect(xcp_rear_button_, SIGNAL(clicked()), this, SLOT(showXcpRearWindow()));

  play_button_->setEnabled(false);
  stop_button_->setEnabled(false);
  frame_spinner_->setEnabled(false);
  step_spinner_->setEnabled(false);
  step_forward_button_->setEnabled(false);
  step_backward_button_->setEnabled(false);
  play_rate_combo_->setEnabled(false);
  frame_slider_->setEnabled(false);
  select_main_radar_->setEnabled(false);
  scene_mode_checkbox_->setEnabled(false);

  bag_reader_->setMessageCallback([this](const std::vector<rosbag::MessageInstance>& frame_msg,  
                                         const int& frame_number,
                                         const std::vector<int>& msg_flag
                                        ) {
    publishClosestMessages(frame_msg,frame_number,msg_flag);
    if (kpi_batch_running_)
    {
      QMetaObject::invokeMethod(this, [this]() {
        resetKpiBatchPlaybackWatchdog();
      }, Qt::QueuedConnection);
    }
    if (!kpi_batch_running_)
    {
      QMetaObject::invokeMethod(this, [this]() {
        updateSliderAndSpinner();
      }, Qt::QueuedConnection);
    }
  });//设置回调：当BagReader有新帧数据时，发布ROS消息并更新UI

  bag_reader_->setPlaybackFinishedCallback([this]() {
    QMetaObject::invokeMethod(this, [this]() {
      handlePlaybackFinished();
    }, Qt::QueuedConnection);
  });

  bag_reader_->setUpdateProgressBarCallback([this](float value){
    // BagReader may report progress from its worker thread.  QWidget methods
    // must only run in the Qt GUI thread.
    QMetaObject::invokeMethod(this, [this, value]() {
      progress_bar_->setValue(value);
      progress_bar_->repaint();
    }, Qt::QueuedConnection);
  });
  bContinuePlayFlag = false;
  bSPFlag = false;


  select_main_radar_->setCurrentIndex(3);

  // Configure RViz as a player-only window after all docks are created.
  // Avoid changing native top-level window flags or resizing QMainWindow here:
  // either operation can recreate/resize OGRE's OpenGL surface and is unstable
  // in remote X11/XRDP sessions.
  QTimer::singleShot(0, this, [this]() {
    // 隐藏 rviz 主窗口里所有与本插件无关的部件：3D 渲染区、
    // Displays/Views/Time 等其它 Dock、菜单栏、工具栏、状态栏，
    // 只保留本插件面板。
    QWidget* w = this->parentWidget();
    QMainWindow* main_window = nullptr;
    while (w)
    {
      main_window = qobject_cast<QMainWindow*>(w);
      if (main_window)
      {
        break;
      }
      w = w->parentWidget();
    }
    if (main_window)
    {
      QDockWidget* my_dock = nullptr;
      const auto docks = main_window->findChildren<QDockWidget*>();
      for (QDockWidget* dock : docks)
      {
        if (dock->isAncestorOf(this))
        {
          my_dock = dock;
          continue;
        }
        dock->hide();
      }

      if (QWidget* central = main_window->centralWidget())
      {
        central->hide();
      }

      if (main_window->menuBar())
      {
        main_window->menuBar()->hide();
      }
      if (main_window->statusBar())
      {
        main_window->statusBar()->hide();
      }
      for (QToolBar* tb : main_window->findChildren<QToolBar*>())
      {
        tb->hide();
      }

      if (my_dock)
      {
        my_dock->show();
        my_dock->raise();
        my_dock->setTitleBarWidget(nullptr);
      }

      if (content_widget_)
      {
        content_widget_->updateGeometry();
        content_widget_->update();
      }
      updateGeometry();
      update();
    }
  });
}

QSize MyRvizPlugin::sizeHint() const
{
  if (content_widget_)
  {
    return content_widget_->sizeHint();
  }
  return rviz::Panel::sizeHint();
}

MyRvizPlugin::~MyRvizPlugin()
{
  spinner_->stop();
  bag_reader_->stopBag();
  delete bag_reader_;
  delete spinner_;
}

int MyRvizPlugin::frameCountForRadar(int radar_index) const
{
  switch (radar_index)
  {
    case 0:
      return frame_count0;
    case 1:
      return frame_count1;
    case 2:
      return frame_count2;
    case 3:
      return frame_count3;
    case 4:
      return frame_count4;
    default:
      return 0;
  }
}

int MyRvizPlugin::resolvePlayableMainRadarIndex() const
{
  if (frameCountForRadar(mainRadarIndex_) > 0)
  {
    return mainRadarIndex_;
  }

  for (int radar_index = 0; radar_index <= 4; ++radar_index)
  {
    if (frameCountForRadar(radar_index) > 0)
    {
      return radar_index;
    }
  }

  return -1;
}

void MyRvizPlugin::updateFrameControlsForSelectedRadar()
{
  const bool scene_mode = scene_mode_checkbox_ && scene_mode_checkbox_->isChecked()
                          && !kpi_batch_running_ && !folder_mode_;
  const int item_count = scene_mode
      ? frameCountForRadar(mainRadarIndex_)
      : bag_reader_->getPlaybackEventCount();

  const QSignalBlocker spinner_blocker(frame_spinner_);
  const QSignalBlocker slider_blocker(frame_slider_);
  frame_spinner_->setMaximum(item_count > 0 ? item_count : 0);
  frame_slider_->setMaximum(item_count > 0 ? item_count : 0);
  if (frame_spinner_->value() >= item_count)
  {
    frame_spinner_->setValue(0);
    frame_slider_->setValue(0);
  }
}

void MyRvizPlugin::sceneModeChanged(bool enabled)
{
  if (enabled && (kpi_batch_running_ || folder_mode_))
  {
    const QSignalBlocker blocker(scene_mode_checkbox_);
    scene_mode_checkbox_->setChecked(false);
    QMessageBox::information(this, "Scene Mode",
                             "Scene Mode is only available for single-bag debugging. KPI batch uses strict LGU Event mode.");
    return;
  }

  if (!enabled)
  {
    std::lock_guard<std::mutex> lock(pending_scene_service_mutex_);
    scene_dispatch_active_ = false;
    pending_scene_frame_ids_.fill(-1);
    pending_scene_completed_.fill(false);
  }

  updateFrameControlsForSelectedRadar();
  {
    const QSignalBlocker spinner_blocker(frame_spinner_);
    const QSignalBlocker slider_blocker(frame_slider_);
    frame_spinner_->setValue(0);
    frame_slider_->setValue(0);
  }
  frame_id_label_->setText(enabled
      ? "Scene Frame Index: N/A  Anchor Radar: N/A  SceneBagTime(CN): N/A  SceneBagRosSec: N/A"
      : "LGU Event Index: N/A  Active Radar: N/A  EventBagTime(CN): N/A  EventBagRosSec: N/A");
}

void MyRvizPlugin::handlePlaybackFinished()
{
  pending_service_radar_id_ = -1;
  pending_service_frame_id_ = -1;
  {
    std::lock_guard<std::mutex> lock(pending_scene_service_mutex_);
    for (auto& pending_frames : pending_event_frame_ids_)
    {
      pending_frames.clear();
    }
    scene_dispatch_active_ = false;
    pending_scene_frame_ids_.fill(-1);
    pending_scene_completed_.fill(false);
  }

  internal_stop_request_ = true;
  stopKpiBatchPlaybackWatchdog();
  stopBag();
  internal_stop_request_ = false;

  if (!folder_mode_)
  {
    return;
  }

  ROS_INFO("Reached end of time-ordered LGU playback %d/%lu: %s",
           current_bag_index_ + 1, bag_files_.size(),
           bag_files_[current_bag_index_].c_str());

  if (kpi_batch_running_)
  {
    runKpiExportForCurrentBag();
  }

  if (current_bag_index_ < static_cast<int>(bag_files_.size()) - 1)
  {
    ROS_INFO("loading next bag file %d/%lu: %s", current_bag_index_ + 2,
             bag_files_.size(), bag_files_[current_bag_index_ + 1].c_str());
    readBagFile();
    QTimer::singleShot(1000, this, [this]() {
      ROS_INFO("Starting playback for new bag file (index: %d)", current_bag_index_);
      bContinuePlayFlag = true;
      playBag();
    });
    return;
  }

  ROS_WARN("No more bag files to load (%lu files processed)", bag_files_.size());
  current_bag_label_->setText("Current Bag: No more files");
  if (kpi_batch_running_)
  {
    const QString done_msg = kpi_pair_mode_active_
        ? QString("KPI FrameSync batch playback finished.\nOutput dir:\n%1")
            .arg(kpi_output_dir_.isEmpty() ? "N/A" : kpi_output_dir_)
        : QString("Bag-only ADAS trigger batch playback finished.\nIntermediate output dir:\n%1")
            .arg(kpi_output_dir_.isEmpty() ? "N/A" : kpi_output_dir_);
    finishKpiBatchWithMessage(done_msg);
  }

  folder_mode_ = false;
  current_bag_index_ = -1;
  bag_files_.clear();
  bag_csv_files_.clear();
  bag_file_path_->clear();
  current_loaded_bag_path_.clear();
  public_can_ch3_last_text_.clear();
  public_can_ch2_last_text_.clear();
  xcp_front_last_text_.clear();
  xcp_rear_last_text_.clear();
  public_can_ch3_has_msg_ = false;
  public_can_ch2_has_msg_ = false;
  public_can_ch3_last_msg_index_ = -1;
  public_can_ch2_last_msg_index_ = -1;
  updatePublicCanTree(public_can_ch3_tree_, "No /rear/signals message loaded.");
  updatePublicCanTree(public_can_ch2_tree_, "No /front/signals message loaded.");
  updatePublicCanText(xcp_front_text_, "No front XCP message loaded.");
  updatePublicCanText(xcp_rear_text_, "No rear XCP message loaded.");
  current_csv_label_->setText("Matched CSV: N/A");
  warning_topic_label_->setText("Warning Topic: N/A");
  warning_summary_text_->clear();
  manual_tag_topic_label_->setText("Manual Tag Topic: N/A");
  manual_tag_summary_text_->clear();
  scene_mode_checkbox_->setEnabled(false);
}

void MyRvizPlugin::resetAlgoWarningTrace()
{
  std::lock_guard<std::mutex> lock(algo_warning_trace_mutex_);
  algo_warning_trace_.clear();
  last_lgu_stamp_sec_.fill(0.0);
  last_lgu_frame_id_.fill(-1);
  for (auto& stamps_by_frame : lgu_stamp_by_frame_)
  {
    stamps_by_frame.clear();
  }
  last_main_radar_stamp_sec_ = 0.0;
  last_main_frame_id_ = -1;
  pending_service_radar_id_ = -1;
  pending_service_frame_id_ = -1;
  {
    std::lock_guard<std::mutex> lock(pending_scene_service_mutex_);
    for (auto& pending_frames : pending_event_frame_ids_)
    {
      pending_frames.clear();
    }
    scene_dispatch_active_ = false;
    pending_scene_frame_ids_.fill(-1);
    pending_scene_completed_.fill(false);
  }
}

void MyRvizPlugin::onAlgoWarningForKpi(const std_msgs::UInt8MultiArray::ConstPtr& msg)
{
  if (use_warning_status_with_frame_)
  {
    return;
  }
  if (!kpi_batch_running_ || !msg)
  {
    return;
  }
  if (msg->data.size() < 16)
  {
    return;
  }

  const int radar_id = static_cast<int>(msg->data[0]);
  if (radar_id < 1 || radar_id > 4)
  {
    return;
  }

  AlgoWarningSample sample;
  sample.radar_id = radar_id;
  for (int i = 0; i < 15; ++i)
  {
    sample.bits[i] = static_cast<int>(msg->data[i + 1]);
  }

  {
    std::lock_guard<std::mutex> lock(algo_warning_trace_mutex_);
    sample.from_main_fallback = false;
    double event_sec = last_lgu_stamp_sec_[radar_id];
    int frame_id = last_lgu_frame_id_[radar_id];
    if (event_sec <= 0.0)
    {
      event_sec = last_main_radar_stamp_sec_;
      frame_id = last_main_frame_id_;
      sample.from_main_fallback = true;
    }
    if (event_sec <= 0.0)
    {
      return;
	    }
	    sample.event_sec = event_sec;
	    sample.frame_id = frame_id;
	    for (auto it = algo_warning_trace_.rbegin(); it != algo_warning_trace_.rend(); ++it)
	    {
	      if (it->radar_id == sample.radar_id && it->frame_id == sample.frame_id)
	      {
	        if (it->bits == sample.bits)
	        {
	          return;
	        }
	        break;
	      }
	    }
	    algo_warning_trace_.push_back(sample);
	  }
	}

void MyRvizPlugin::onAlgoWarningWithFrameForKpi(const std_msgs::UInt32MultiArray::ConstPtr& msg)
{
  if (!kpi_batch_running_ || !msg)
  {
    return;
  }
  if (msg->data.size() < 17)
  {
    return;
  }

  const int radar_id = static_cast<int>(msg->data[0]);
  if (radar_id < 1 || radar_id > 4)
  {
    return;
  }

  AlgoWarningSample sample;
  sample.radar_id = radar_id;
  sample.frame_id = static_cast<int>(msg->data[1]);
  sample.from_main_fallback = false;
  for (int i = 0; i < 15; ++i)
  {
    sample.bits[i] = static_cast<int>(msg->data[i + 2]);
  }

  {
    std::lock_guard<std::mutex> lock(algo_warning_trace_mutex_);
    double event_sec = 0.0;
    const auto stamp_it = lgu_stamp_by_frame_[radar_id].find(sample.frame_id);
    if (stamp_it != lgu_stamp_by_frame_[radar_id].end())
    {
      event_sec = stamp_it->second;
    }
    else
    {
      event_sec = last_lgu_stamp_sec_[radar_id];
    }
    if (event_sec <= 0.0)
    {
      event_sec = last_main_radar_stamp_sec_;
      sample.from_main_fallback = true;
    }
    if (event_sec <= 0.0)
	    {
	      return;
	    }
	    sample.event_sec = event_sec;
	    for (auto it = algo_warning_trace_.rbegin(); it != algo_warning_trace_.rend(); ++it)
	    {
	      if (it->radar_id == sample.radar_id && it->frame_id == sample.frame_id)
	      {
	        if (it->bits == sample.bits)
	        {
	          return;
	        }
	        break;
	      }
	    }
	    algo_warning_trace_.push_back(sample);
	  }
	}

QString MyRvizPlugin::writeAlgoWarningTraceCsv(const QString& bag_base_name)
{
  if (kpi_output_dir_.isEmpty())
  {
    return QString();
  }

  const QString trace_path = QDir(kpi_output_dir_).absoluteFilePath(
      bag_base_name + "_algo_warning_trace.csv");
  QFile file(trace_path);
  if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate | QIODevice::Text))
  {
    return QString();
  }

  std::vector<AlgoWarningSample> samples;
  {
    std::lock_guard<std::mutex> lock(algo_warning_trace_mutex_);
    samples = algo_warning_trace_;
  }
  std::sort(samples.begin(), samples.end(), [](const AlgoWarningSample& a, const AlgoWarningSample& b) {
    if (a.event_sec == b.event_sec)
    {
      return a.radar_id < b.radar_id;
    }
    return a.event_sec < b.event_sec;
  });

  QTextStream ts(&file);
  ts << "event_sec,radar_id,frame_id";
  for (int i = 1; i <= 15; ++i)
  {
    ts << ",w" << i;
  }
  ts << "\n";

  for (const auto& s : samples)
  {
    ts << QString::number(s.event_sec, 'f', 6) << "," << s.radar_id << "," << s.frame_id;
    for (int i = 0; i < 15; ++i)
    {
      ts << "," << s.bits[i];
    }
    ts << "\n";
  }
  file.close();
  return trace_path;
}

QString MyRvizPlugin::formatPublicCanMessage(const common_can_signal_publisher_rvizbag::PublicCanFrontSignals& msg,
                                             const QString& topic,
                                             int msg_index,
                                             const ros::Time& bag_time) const
{
  return formatPublicCanMessageImpl(msg, topic, msg_index, bag_time);
}

QString MyRvizPlugin::formatPublicCanMessage(const common_can_signal_publisher_rvizbag::PublicCanRearSignals& msg,
                                             const QString& topic,
                                             int msg_index,
                                             const ros::Time& bag_time) const
{
  return formatPublicCanMessageImpl(msg, topic, msg_index, bag_time);
}

void MyRvizPlugin::showPublicCanWindow(QDialog*& dialog,
                                       QTextEdit*& text_edit,
                                       const QString& title,
                                       const QString& last_text)
{
  if (!dialog)
  {
    dialog = new QDialog(this);
    dialog->setWindowTitle(title);
    dialog->resize(900, 700);

    QVBoxLayout* layout = new QVBoxLayout(dialog);
    text_edit = new QTextEdit(dialog);
    text_edit->setReadOnly(true);
    text_edit->setLineWrapMode(QTextEdit::NoWrap);
    text_edit->setFont(QFontDatabase::systemFont(QFontDatabase::FixedFont));
    text_edit->setStyleSheet("QTextEdit { color: #000000; background: #ffffff; }");
    layout->addWidget(text_edit);
    dialog->setLayout(layout);
  }

  if (text_edit)
  {
    text_edit->setPlainText(last_text.isEmpty() ? "No public CAN message selected yet." : last_text);
  }
  dialog->show();
  dialog->raise();
  dialog->activateWindow();
}

void MyRvizPlugin::updatePublicCanText(QTextEdit* text_edit, const QString& text)
{
  if (!text_edit)
  {
    return;
  }

  QMetaObject::invokeMethod(text_edit, [text_edit, text]() {
    text_edit->setPlainText(text);
  }, Qt::QueuedConnection);
}

void MyRvizPlugin::populatePublicCanTree(QTreeWidget* tree_widget, const QString& text) const
{
  if (!tree_widget)
  {
    return;
  }

  std::set<QString> expanded_items;
  collectExpandedTopLevelItems(tree_widget, expanded_items);

  tree_widget->clear();
  tree_widget->setColumnCount(2);
  tree_widget->setHeaderLabels(QStringList() << "Group / Signal" << "Value");

  if (text.trimmed().isEmpty() || text.startsWith("No "))
  {
    QTreeWidgetItem* item = new QTreeWidgetItem(tree_widget);
    item->setText(0, text.trimmed().isEmpty() ? "No public CAN message selected yet." : text.trimmed());
    return;
  }

  QTreeWidgetItem* summary = new QTreeWidgetItem(tree_widget);
  summary->setText(0, "Summary");
  QTreeWidgetItem* ros_header = new QTreeWidgetItem(tree_widget);
  ros_header->setText(0, "ROS Header");
  QTreeWidgetItem* valid_array = new QTreeWidgetItem(tree_widget);
  valid_array->setText(0, "signal_valid");
  QTreeWidgetItem* age_array = new QTreeWidgetItem(tree_widget);
  age_array->setText(0, "signal_age_ms");
  QTreeWidgetItem* other = new QTreeWidgetItem(tree_widget);
  other->setText(0, "Other Fields");

  std::map<QString, QTreeWidgetItem*> id_groups;
  QTreeWidgetItem* current_parent = summary;
  bool after_separator = false;
  bool inside_header = false;

  const QStringList lines = text.split('\n');
  for (const QString& raw_line : lines)
  {
    const QString line = raw_line.trimmed();
    if (line.isEmpty())
    {
      continue;
    }
    if (line.startsWith("----------------------------------------"))
    {
      after_separator = true;
      current_parent = other;
      continue;
    }

    const int colon = line.indexOf(':');
    if (colon < 0)
    {
      addTreeChild(current_parent, line, "");
      continue;
    }

    const QString key = line.left(colon).trimmed();
    const QString value = line.mid(colon + 1).trimmed();

    if (!after_separator)
    {
      addTreeChild(summary, key, value);
      continue;
    }

    if (key == "header")
    {
      inside_header = true;
      current_parent = ros_header;
      continue;
    }
    if (key == "signal_valid_flat")
    {
      inside_header = false;
      addArrayChildren(valid_array, value);
      continue;
    }
    if (key == "signal_age_ms_flat")
    {
      inside_header = false;
      addArrayChildren(age_array, value);
      continue;
    }
    if (key == "signal_valid" || key == "signal_age_ms")
    {
      inside_header = false;
      // The default ROS printer may wrap large arrays in a format that is hard
      // to parse reliably. Prefer the explicit *_flat lines emitted above.
      continue;
    }

    const QString group_title = publicCanSignalGroupTitle(key);
    if (!group_title.isEmpty())
    {
      inside_header = false;
      QTreeWidgetItem*& group = id_groups[group_title];
      if (!group)
      {
        group = new QTreeWidgetItem(tree_widget);
        group->setText(0, group_title);
      }
      addTreeChild(group, key, value);
      continue;
    }

    addTreeChild(inside_header ? ros_header : other, key, value);
  }

  for (int i = 0; i < tree_widget->topLevelItemCount(); ++i)
  {
    QTreeWidgetItem* item = tree_widget->topLevelItem(i);
    if (!item)
    {
      continue;
    }
    item->setExpanded(item == summary || expanded_items.count(item->text(0)) > 0);
  }
  tree_widget->resizeColumnToContents(0);
  tree_widget->header()->setStretchLastSection(true);
}

void MyRvizPlugin::showPublicCanTreeWindow(QDialog*& dialog,
                                           QTreeWidget*& tree_widget,
                                           const QString& title,
                                           const QString& last_text)
{
  if (!dialog)
  {
    dialog = new QDialog(this);
    dialog->setWindowTitle(title);
    dialog->resize(980, 760);

    QVBoxLayout* layout = new QVBoxLayout(dialog);
    tree_widget = new QTreeWidget(dialog);
    tree_widget->setAlternatingRowColors(true);
    tree_widget->setUniformRowHeights(true);
    tree_widget->setRootIsDecorated(true);
    tree_widget->setStyleSheet("QTreeWidget { color: #000000; background: #ffffff; }");
    layout->addWidget(tree_widget);
    dialog->setLayout(layout);
  }

  populatePublicCanTree(tree_widget, last_text.isEmpty() ? "No public CAN message selected yet." : last_text);
  dialog->show();
  dialog->raise();
  dialog->activateWindow();
}

void MyRvizPlugin::updatePublicCanTree(QTreeWidget* tree_widget, const QString& text)
{
  if (!tree_widget)
  {
    return;
  }

  QMetaObject::invokeMethod(tree_widget, [this, tree_widget, text]() {
    populatePublicCanTree(tree_widget, text);
  }, Qt::QueuedConnection);
}

void MyRvizPlugin::showPublicCanCh3Window()
{
  if (public_can_ch3_has_msg_)
  {
    public_can_ch3_last_text_ = formatPublicCanMessage(public_can_ch3_last_msg_,
                                                       kPublicCanRearTopic,
                                                       public_can_ch3_last_msg_index_,
                                                       public_can_ch3_last_bag_time_);
  }
  showPublicCanTreeWindow(public_can_ch3_dialog_,
                          public_can_ch3_tree_,
                          "Public CAN Rear - /rear/signals",
                          public_can_ch3_last_text_);
}

void MyRvizPlugin::showPublicCanCh2Window()
{
  if (public_can_ch2_has_msg_)
  {
    public_can_ch2_last_text_ = formatPublicCanMessage(public_can_ch2_last_msg_,
                                                       kPublicCanFrontTopic,
                                                       public_can_ch2_last_msg_index_,
                                                       public_can_ch2_last_bag_time_);
  }
  showPublicCanTreeWindow(public_can_ch2_dialog_,
                          public_can_ch2_tree_,
                          "Public CAN Front - /front/signals",
                          public_can_ch2_last_text_);
}

void MyRvizPlugin::showXcpFrontWindow()
{
  showPublicCanWindow(xcp_front_dialog_,
                      xcp_front_text_,
                      "XCP Front - /wf/ego_car_info/front_left|front_right/parsed",
                      xcp_front_last_text_);
}

void MyRvizPlugin::showXcpRearWindow()
{
  showPublicCanWindow(xcp_rear_dialog_,
                      xcp_rear_text_,
                      "XCP Rear - /wf/ego_car_info/rear_left|rear_right/parsed",
                      xcp_rear_last_text_);
}

int MyRvizPlugin::collectAdasTriggersForCurrentBag(const QString& bag_name, const QString& bag_path)
{
  std::vector<AlgoWarningSample> samples;
  {
    std::lock_guard<std::mutex> lock(algo_warning_trace_mutex_);
    samples = algo_warning_trace_;
  }

  std::sort(samples.begin(), samples.end(), [](const AlgoWarningSample& a, const AlgoWarningSample& b) {
    if (a.event_sec == b.event_sec)
    {
      return a.radar_id < b.radar_id;
    }
    return a.event_sec < b.event_sec;
  });

  int count = 0;
  for (const auto& sample : samples)
  {
    bool has_trigger = false;
    for (int i = 0; i < 15; ++i)
    {
      if (sample.bits[static_cast<size_t>(i)] > 0)
      {
        has_trigger = true;
        break;
      }
    }
    if (!has_trigger)
    {
      continue;
    }

    AdasBatchRow row;
    row.bag_name = bag_name;
    row.bag_path = bag_path;
    row.event_sec = sample.event_sec;
    row.radar_id = sample.radar_id;
    row.frame_id = sample.frame_id;
    row.time_source = sample.from_main_fallback ? "main_radar_fallback" : "lgu_radar_stamp";
    row.active_warnings = activeAdasWarnings(sample.bits);
    row.bits = sample.bits;
    adas_batch_rows_.push_back(row);
    ++count;
  }

  return count;
}

QString MyRvizPlugin::writeAdasBatchReportCsv()
{
  if (kpi_output_dir_.isEmpty())
  {
    return QString();
  }

  const QString csv_path = QDir(kpi_output_dir_).absoluteFilePath("batch_adas_trigger_report.csv");
  QFile file(csv_path);
  if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate | QIODevice::Text))
  {
    return QString();
  }

  QTextStream ts(&file);
  auto csv_escape = [](const QString& value) {
    QString out = value;
    out.replace("\"", "\"\"");
    return QString("\"%1\"").arg(out);
  };

  ts << "bag_name,bag_path,event_ros_sec,event_gui_time_utc8,radar_id,frame_id,time_source,active_warnings";
  for (int i = 0; i < 15; ++i)
  {
    ts << ",w" << (i + 1) << "_" << adasWarningName(i);
  }
  ts << "\n";

  for (const auto& row : adas_batch_rows_)
  {
    ros::Time event_ros_time;
    event_ros_time.fromSec(row.event_sec);
    boost::posix_time::ptime gui_time = event_ros_time.toBoost() + boost::posix_time::hours(8);
    const std::string gui_time_str = boost::posix_time::to_simple_string(gui_time);

    ts << csv_escape(row.bag_name) << ","
       << csv_escape(row.bag_path) << ","
       << QString::number(row.event_sec, 'f', 6) << ","
       << csv_escape(QString::fromStdString(gui_time_str)) << ","
       << row.radar_id << ","
       << row.frame_id << ","
       << csv_escape(row.time_source) << ","
       << csv_escape(row.active_warnings);
    for (int i = 0; i < 15; ++i)
    {
      ts << "," << row.bits[static_cast<size_t>(i)];
    }
    ts << "\n";
  }
  file.close();
  return csv_path;
}

QString MyRvizPlugin::writeFctbBatchReportCsv()
{
  if (kpi_output_dir_.isEmpty())
  {
    return QString();
  }

  const QString csv_path = QDir(kpi_output_dir_).absoluteFilePath("batch_fctb_trigger_report.csv");
  QFile file(csv_path);
  if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate | QIODevice::Text))
  {
    return QString();
  }

  QTextStream ts(&file);
  auto csv_escape = [](const QString& value) {
    QString out = value;
    out.replace("\"", "\"\"");
    return QString("\"%1\"").arg(out);
  };

  ts << "bag_name,bag_path,event_ros_sec,event_gui_time_utc8,radar_id,frame_id,time_source,left_fctb,right_fctb\n";

  for (const auto& row : adas_batch_rows_)
  {
    const int fctb_l = row.bits[13];
    const int fctb_r = row.bits[14];
    if (fctb_l == 0 && fctb_r == 0)
    {
      continue;
    }

    ros::Time event_ros_time;
    event_ros_time.fromSec(row.event_sec);
    boost::posix_time::ptime gui_time = event_ros_time.toBoost() + boost::posix_time::hours(8);
    const std::string gui_time_str = boost::posix_time::to_simple_string(gui_time);

    ts << csv_escape(row.bag_name) << ","
       << csv_escape(row.bag_path) << ","
       << QString::number(row.event_sec, 'f', 6) << ","
       << csv_escape(QString::fromStdString(gui_time_str)) << ","
       << row.radar_id << ","
       << row.frame_id << ","
       << csv_escape(row.time_source) << ","
       << fctb_l << ","
       << fctb_r << "\n";
  }
  file.close();
  return csv_path;
}

// 服务回调函数：处理客户端请求
bool MyRvizPlugin::handleServiceRequest(wf_srvs_rvizbag::PlaySingleFrame::Request &req,
                            wf_srvs_rvizbag::PlaySingleFrame::Response &res)
{
  bool scene_complete = false;
  bool scene_handled = false;
  int completed_event_radar = -1;

  {
    std::lock_guard<std::mutex> lock(pending_scene_service_mutex_);
    if (scene_dispatch_active_)
    {
      scene_handled = true;
      if (req.radar_pos < 0 || req.radar_pos >= static_cast<int>(pending_scene_frame_ids_.size())
          || pending_scene_frame_ids_[req.radar_pos] < 0
          || pending_scene_frame_ids_[req.radar_pos] != req.frame_id)
      {
        ROS_WARN("[FRAME_PLAYER] ignoring mismatched scene callback: radar=%d frame=%d",
                 req.radar_pos, req.frame_id);
        res.success = false;
        return true;
      }

      if (req.status == 0)
      {
        res.success = true;
        return true;
      }
      if (req.status != 1)
      {
        res.success = false;
        return true;
      }

      pending_scene_completed_[req.radar_pos] = true;
      scene_complete = true;
      for (size_t radar = 0; radar < pending_scene_frame_ids_.size(); ++radar)
      {
        if (pending_scene_frame_ids_[radar] >= 0 && !pending_scene_completed_[radar])
        {
          scene_complete = false;
          break;
        }
      }
      if (scene_complete)
      {
        scene_dispatch_active_ = false;
      }
      res.success = true;
    }
    else
    {
      if (req.radar_pos < 0 || req.radar_pos >= static_cast<int>(pending_event_frame_ids_.size()))
      {
        ROS_WARN("[FRAME_PLAYER] invalid event callback radar=%d frame=%d status=%d",
                 req.radar_pos, req.frame_id, req.status);
        res.success = false;
        return true;
      }

      const std::deque<int>& pending_frames = pending_event_frame_ids_[req.radar_pos];
      const int expected_frame = pending_frames.empty() ? -1 : pending_frames.front();
      if (expected_frame < 0 || expected_frame != req.frame_id)
      {
        ROS_WARN("[FRAME_PLAYER] ignoring stale/mismatched event callback: radar=%d frame=%d expected=%d",
                 req.radar_pos, req.frame_id, expected_frame);
        res.success = false;
        return true;
      }

      if (req.status == 0)
      {
        ROS_INFO("Received data: radar_pos = %d, frame_id = %d", req.radar_pos, req.frame_id);
        res.success = true;
        return true;
      }
      if (req.status != 1)
      {
        ROS_WARN("Play single frame service error: status=%d", req.status);
        res.success = false;
        return true;
      }

      ROS_INFO("Finish process: radar_pos = %d, frame_id = %d", req.radar_pos, req.frame_id);
      pending_event_frame_ids_[req.radar_pos].pop_front();
      completed_event_radar = req.radar_pos;

      pending_service_radar_id_ = -1;
      pending_service_frame_id_ = -1;
      for (size_t radar = 0; radar < pending_event_frame_ids_.size(); ++radar)
      {
        if (!pending_event_frame_ids_[radar].empty())
        {
          pending_service_radar_id_ = static_cast<int>(radar);
          pending_service_frame_id_ = pending_event_frame_ids_[radar].front();
          break;
        }
      }
      res.success = true;
    }
  }

  if (scene_handled)
  {
    if (scene_complete)
    {
      ROS_INFO("[FRAME_PLAYER] all radar callbacks completed for current debug scene");
      bag_reader_->setFinishProcessFlag(true);
    }
    return true;
  }

  if (completed_event_radar >= 0)
  {
    bag_reader_->setRadarProcessComplete(completed_event_radar);
    if (kpi_batch_running_)
    {
      QMetaObject::invokeMethod(this, [this]() {
        resetKpiBatchPlaybackWatchdog();
      }, Qt::QueuedConnection);
    }
  }
  return true;
}

void MyRvizPlugin::publishClosestMessages(const std::vector<rosbag::MessageInstance>& frame_msg,  
                                          const int& frame_number,
                                          const std::vector<int>& msg_flag
                                          )
{
  ROS_INFO("[FRAME_PLAYER] publishClosestMessages frame=%d frame_msg.size=%zu msg_flag.size=%zu", frame_number, frame_msg.size(), msg_flag.size());
  auto get_frame_msg_by_slot = [&](int slot) -> const rosbag::MessageInstance* {
    if (slot < 0 || slot >= static_cast<int>(msg_flag.size()) || msg_flag[slot] < 0)
    {
      return nullptr;
    }
    if (slot >= static_cast<int>(frame_msg.size()))
    {
      ROS_ERROR("[FRAME_PLAYER] slot out of range: slot=%d frame_msg.size=%zu msg_flag.size=%zu", slot, frame_msg.size(), msg_flag.size());
      return nullptr;
    }
    return &frame_msg[slot];
  };

  const ros::Time main_time = bag_reader_->getCurrentSelectionTime();
  const int active_radar_id = bag_reader_->getCurrentSelectionRadar();
  const bool scene_mode = bag_reader_->isCurrentSelectionScene();
  std::array<int, 5> dispatched_frame_ids;
  std::array<double, 5> dispatched_event_secs;
  dispatched_frame_ids.fill(-1);
  dispatched_event_secs.fill(0.0);
  for (int radar_id = 0; radar_id <= 4; ++radar_id)
  {
    if (const rosbag::MessageInstance* radar_slot = get_frame_msg_by_slot(radar_id))
    {
      const boost::shared_ptr<arbe_msgs_rvizbag::wfAutosarData> radar_lgu =
          radar_slot->instantiate<arbe_msgs_rvizbag::wfAutosarData>();
      if (radar_lgu)
      {
        dispatched_frame_ids[radar_id] = static_cast<int>(radar_lgu->frameID);
        dispatched_event_secs[radar_id] = radar_lgu->header.stamp.toSec() > 0.0
            ? radar_lgu->header.stamp.toSec()
            : radar_slot->getTime().toSec();
      }
    }
  }
  int active_frame_id = -1;
  double active_lgu_stamp_sec = 0.0;
  if (active_radar_id >= 0 && active_radar_id < static_cast<int>(dispatched_frame_ids.size()))
  {
    active_frame_id = dispatched_frame_ids[active_radar_id];
    active_lgu_stamp_sec = dispatched_event_secs[active_radar_id];
  }

  if (active_radar_id < 0 || active_frame_id < 0)
  {
    ROS_ERROR("[FRAME_PLAYER] invalid time-ordered LGU event: event=%d radar=%d frame=%d",
              frame_number, active_radar_id, active_frame_id);
    if (scene_mode)
    {
      bag_reader_->setFinishProcessFlag(true);
    }
    else
    {
      bag_reader_->setRadarProcessComplete(active_radar_id);
    }
    return;
  }

  // Set expected callbacks before publishing, so fast algorithm responses cannot race us.
  if (scene_mode)
  {
    std::lock_guard<std::mutex> lock(pending_scene_service_mutex_);
    for (auto& pending_frames : pending_event_frame_ids_)
    {
      pending_frames.clear();
    }
    pending_scene_frame_ids_.fill(-1);
    pending_scene_completed_.fill(false);
    for (int radar_id = 0; radar_id <= 4; ++radar_id)
    {
      if (dispatched_frame_ids[radar_id] >= 0)
      {
        pending_scene_frame_ids_[radar_id] = dispatched_frame_ids[radar_id];
      }
    }
    scene_dispatch_active_ = true;
    pending_service_radar_id_ = -1;
    pending_service_frame_id_ = -1;
  }
  else
  {
    std::lock_guard<std::mutex> lock(pending_scene_service_mutex_);
    scene_dispatch_active_ = false;
    pending_event_frame_ids_[active_radar_id].push_back(active_frame_id);
    pending_service_radar_id_ = -1;
    pending_service_frame_id_ = -1;
    for (size_t radar = 0; radar < pending_event_frame_ids_.size(); ++radar)
    {
      if (!pending_event_frame_ids_[radar].empty())
      {
        pending_service_radar_id_ = static_cast<int>(radar);
        pending_service_frame_id_ = pending_event_frame_ids_[radar].front();
        break;
      }
    }
  }
  {
    std::lock_guard<std::mutex> lock(algo_warning_trace_mutex_);
    for (int radar_id = 0; radar_id <= 4; ++radar_id)
    {
      if (dispatched_frame_ids[radar_id] >= 0 && dispatched_event_secs[radar_id] > 0.0)
      {
        lgu_stamp_by_frame_[radar_id][dispatched_frame_ids[radar_id]] = dispatched_event_secs[radar_id];
      }
    }
  }
  if (main_time.toSec() > 0.0)
  {
    std::lock_guard<std::mutex> lock(algo_warning_trace_mutex_);
    const double trace_time = active_lgu_stamp_sec > 0.0 ? active_lgu_stamp_sec : main_time.toSec();
    last_lgu_stamp_sec_[active_radar_id] = trace_time;
    last_lgu_frame_id_[active_radar_id] = active_frame_id;
    last_main_radar_stamp_sec_ = trace_time;
    last_main_frame_id_ = active_frame_id;
  }

  const rosbag::MessageInstance* car_slot = get_frame_msg_by_slot(12);
  boost::shared_ptr<arbe_msgs_rvizbag::VehStatusOutput> car_status =
      car_slot ? car_slot->instantiate<arbe_msgs_rvizbag::VehStatusOutput>() : boost::shared_ptr<arbe_msgs_rvizbag::VehStatusOutput>();
  if (car_status)
  {
    car_pub_.publish(*car_status);
  }

  QString xcp_front_text = "No front XCP message loaded.";
  QString xcp_rear_text = "No rear XCP message loaded.";
  bool has_xcp_front = false;
  bool has_xcp_rear = false;

  auto append_xcp_section = [](QString& text,
                               bool& has_any,
                               const QString& title,
                               const QString& body) {
    if (!has_any)
    {
      text = title + "\n" + body;
      has_any = true;
      return;
    }
    text += "\n\n" + title + "\n" + body;
  };

  const rosbag::MessageInstance* ego_fl_slot = get_frame_msg_by_slot(13);
  boost::shared_ptr<common_xcp_info_publisher_rvizbag::XcpEgoInfo> ego_fl =
      ego_fl_slot ? ego_fl_slot->instantiate<common_xcp_info_publisher_rvizbag::XcpEgoInfo>() : boost::shared_ptr<common_xcp_info_publisher_rvizbag::XcpEgoInfo>();
  if (ego_fl)
  {
    ego_car_info_front_left_pub_.publish(*ego_fl);
    append_xcp_section(xcp_front_text, has_xcp_front, "Front Left",
                       formatXcpMessageImpl(*ego_fl, "/wf/ego_car_info/front_left/parsed", msg_flag[13], ego_fl_slot->getTime()));
  }

  const rosbag::MessageInstance* ego_fr_slot = get_frame_msg_by_slot(14);
  boost::shared_ptr<common_xcp_info_publisher_rvizbag::XcpEgoInfo> ego_fr =
      ego_fr_slot ? ego_fr_slot->instantiate<common_xcp_info_publisher_rvizbag::XcpEgoInfo>() : boost::shared_ptr<common_xcp_info_publisher_rvizbag::XcpEgoInfo>();
  if (ego_fr)
  {
    ego_car_info_front_right_pub_.publish(*ego_fr);
    append_xcp_section(xcp_front_text, has_xcp_front, "Front Right",
                       formatXcpMessageImpl(*ego_fr, "/wf/ego_car_info/front_right/parsed", msg_flag[14], ego_fr_slot->getTime()));
  }

  const rosbag::MessageInstance* ego_rl_slot = get_frame_msg_by_slot(15);
  boost::shared_ptr<common_xcp_info_publisher_rvizbag::XcpEgoInfo> ego_rl =
      ego_rl_slot ? ego_rl_slot->instantiate<common_xcp_info_publisher_rvizbag::XcpEgoInfo>() : boost::shared_ptr<common_xcp_info_publisher_rvizbag::XcpEgoInfo>();
  if (ego_rl)
  {
    ego_car_info_rear_left_pub_.publish(*ego_rl);
    append_xcp_section(xcp_rear_text, has_xcp_rear, "Rear Left",
                       formatXcpMessageImpl(*ego_rl, "/wf/ego_car_info/rear_left/parsed", msg_flag[15], ego_rl_slot->getTime()));
  }

  const rosbag::MessageInstance* ego_rr_slot = get_frame_msg_by_slot(16);
  boost::shared_ptr<common_xcp_info_publisher_rvizbag::XcpEgoInfo> ego_rr =
      ego_rr_slot ? ego_rr_slot->instantiate<common_xcp_info_publisher_rvizbag::XcpEgoInfo>() : boost::shared_ptr<common_xcp_info_publisher_rvizbag::XcpEgoInfo>();
  if (ego_rr)
  {
    ego_car_info_rear_right_pub_.publish(*ego_rr);
    append_xcp_section(xcp_rear_text, has_xcp_rear, "Rear Right",
                       formatXcpMessageImpl(*ego_rr, "/wf/ego_car_info/rear_right/parsed", msg_flag[16], ego_rr_slot->getTime()));
  }

  QMetaObject::invokeMethod(this, [this, xcp_front_text, xcp_rear_text]() {
    xcp_front_last_text_ = xcp_front_text;
    xcp_rear_last_text_ = xcp_rear_text;
    if (xcp_front_dialog_ && xcp_front_dialog_->isVisible())
    {
      updatePublicCanText(xcp_front_text_, xcp_front_last_text_);
    }
    if (xcp_rear_dialog_ && xcp_rear_dialog_->isVisible())
    {
      updatePublicCanText(xcp_rear_text_, xcp_rear_last_text_);
    }
  }, Qt::QueuedConnection);

  const rosbag::MessageInstance* public_can_ch3_slot = get_frame_msg_by_slot(17);
  if (public_can_ch3_slot)
  {
    boost::shared_ptr<common_can_signal_publisher_rvizbag::PublicCanRearSignals> public_can_ch3 =
        public_can_ch3_slot->instantiate<common_can_signal_publisher_rvizbag::PublicCanRearSignals>();
    if (public_can_ch3)
    {
      public_can_ch3_pub_.publish(*public_can_ch3);
      const int public_can_ch3_index = msg_flag[17];
      const ros::Time public_can_ch3_bag_time = public_can_ch3_slot->getTime();
      const QString public_can_ch3_text = formatPublicCanMessage(*public_can_ch3,
                                                                 kPublicCanRearTopic,
                                                                 public_can_ch3_index,
                                                                 public_can_ch3_bag_time);
      QMetaObject::invokeMethod(this, [this, public_can_ch3_index, public_can_ch3_bag_time, public_can_ch3_text]() {
        public_can_ch3_last_msg_index_ = public_can_ch3_index;
        public_can_ch3_last_bag_time_ = public_can_ch3_bag_time;
        public_can_ch3_last_text_ = public_can_ch3_text;
        public_can_ch3_has_msg_ = true;
        if (public_can_ch3_dialog_ && public_can_ch3_dialog_->isVisible())
        {
          updatePublicCanTree(public_can_ch3_tree_, public_can_ch3_last_text_);
        }
      }, Qt::QueuedConnection);
    }
  }

  const rosbag::MessageInstance* public_can_ch2_slot = get_frame_msg_by_slot(18);
  if (public_can_ch2_slot)
  {
    boost::shared_ptr<common_can_signal_publisher_rvizbag::PublicCanFrontSignals> public_can_ch2 =
        public_can_ch2_slot->instantiate<common_can_signal_publisher_rvizbag::PublicCanFrontSignals>();
    if (public_can_ch2)
    {
      public_can_ch2_pub_.publish(*public_can_ch2);
      const int public_can_ch2_index = msg_flag[18];
      const ros::Time public_can_ch2_bag_time = public_can_ch2_slot->getTime();
      const QString public_can_ch2_text = formatPublicCanMessage(*public_can_ch2,
                                                                 kPublicCanFrontTopic,
                                                                 public_can_ch2_index,
                                                                 public_can_ch2_bag_time);
      QMetaObject::invokeMethod(this, [this, public_can_ch2_index, public_can_ch2_bag_time, public_can_ch2_text]() {
        public_can_ch2_last_msg_index_ = public_can_ch2_index;
        public_can_ch2_last_bag_time_ = public_can_ch2_bag_time;
        public_can_ch2_last_text_ = public_can_ch2_text;
        public_can_ch2_has_msg_ = true;
        if (public_can_ch2_dialog_ && public_can_ch2_dialog_->isVisible())
        {
          updatePublicCanTree(public_can_ch2_tree_, public_can_ch2_last_text_);
        }
      }, Qt::QueuedConnection);
    }
  }

  if (publish_warning_raw_checkbox_->isChecked() && msg_flag[5] >= 0)
  {
    const double warning_max_age_sec = bag_reader_->getWarningMaxAgeSec();
    struct WarningCandidate
    {
      bool has_value = false;
      double dt_to_main_sec = std::numeric_limits<double>::max();
      std_msgs::UInt8MultiArray msg;
    };

    std::array<WarningCandidate, 5> best_warning_per_radar;
    auto select_warning_candidate = [&best_warning_per_radar, &main_time, warning_max_age_sec](
                                      const std_msgs::UInt8MultiArray& warning_status,
                                      const ros::Time& warning_time) {
      if (warning_status.data.empty())
      {
        return;
      }

      const int radar_id = static_cast<int>(warning_status.data[0]);
      if (radar_id < 1 || radar_id > 4)
      {
        return;
      }

      const double dt = (main_time - warning_time).toSec();
      if (dt < 0.0 || dt > warning_max_age_sec)
      {
        return;
      }
      WarningCandidate& candidate = best_warning_per_radar[radar_id];

      if (!candidate.has_value || dt < candidate.dt_to_main_sec)
      {
        candidate.has_value = true;
        candidate.dt_to_main_sec = dt;
        candidate.msg = warning_status;
      }
    };

    const std::vector<rosbag::MessageInstance> nearby_warning_msgs =
        bag_reader_->getWarningMessagesAroundIndex(msg_flag[5], warning_max_age_sec);
    for (const auto& warning_msg : nearby_warning_msgs)
    {
      boost::shared_ptr<std_msgs::UInt8MultiArray> warning_status = warning_msg.instantiate<std_msgs::UInt8MultiArray>();
      if (!warning_status)
      {
        continue;
      }
      select_warning_candidate(*warning_status, warning_msg.getTime());
    }

    for (int radar_id = 1; radar_id <= 4; ++radar_id)
    {
      const WarningCandidate& candidate = best_warning_per_radar[radar_id];
      if (candidate.has_value)
      {
        warning_pub_.publish(candidate.msg);
      }
    }
  }

  boost::posix_time::time_duration time_offset(8, 0, 0);
  {
    const rosbag::MessageInstance* pointcloud_slot0 = get_frame_msg_by_slot(0);
    boost::shared_ptr<arbe_msgs_rvizbag::wfAutosarData> pointcloud_data0 =
        pointcloud_slot0 ? pointcloud_slot0->instantiate<arbe_msgs_rvizbag::wfAutosarData>() : boost::shared_ptr<arbe_msgs_rvizbag::wfAutosarData>();
    if (pointcloud_data0)
    {
      pointcloud_pub0_.publish(*pointcloud_data0);
    }
    else
    {
      ROS_INFO("pointcloud_data0 is null");
    }

    const rosbag::MessageInstance* pointcloud_slot1 = get_frame_msg_by_slot(1);
    boost::shared_ptr<arbe_msgs_rvizbag::wfAutosarData> pointcloud_data1 =
        pointcloud_slot1 ? pointcloud_slot1->instantiate<arbe_msgs_rvizbag::wfAutosarData>() : boost::shared_ptr<arbe_msgs_rvizbag::wfAutosarData>();
    if (pointcloud_data1)
    {
      if (pointcloud_data1->header.stamp.toSec() > 0.0)
      {
        std::lock_guard<std::mutex> lock(algo_warning_trace_mutex_);
        last_lgu_stamp_sec_[1] = pointcloud_data1->header.stamp.toSec();
        last_lgu_frame_id_[1] = static_cast<int>(pointcloud_data1->frameID);
        if (mainRadarIndex_ == 1)
        {
          last_main_radar_stamp_sec_ = pointcloud_data1->header.stamp.toSec();
          last_main_frame_id_ = static_cast<int>(pointcloud_data1->frameID);
        }
      }
      pointcloud_pub1_.publish(*pointcloud_data1);
    }
    else
    {
      ROS_INFO("pointcloud_data1 is null");
    }

    const rosbag::MessageInstance* pointcloud_slot2 = get_frame_msg_by_slot(2);
    boost::shared_ptr<arbe_msgs_rvizbag::wfAutosarData> pointcloud_data2 =
        pointcloud_slot2 ? pointcloud_slot2->instantiate<arbe_msgs_rvizbag::wfAutosarData>() : boost::shared_ptr<arbe_msgs_rvizbag::wfAutosarData>();
    if (pointcloud_data2)
    {
      if (pointcloud_data2->header.stamp.toSec() > 0.0)
      {
        std::lock_guard<std::mutex> lock(algo_warning_trace_mutex_);
        last_lgu_stamp_sec_[2] = pointcloud_data2->header.stamp.toSec();
        last_lgu_frame_id_[2] = static_cast<int>(pointcloud_data2->frameID);
        if (mainRadarIndex_ == 2)
        {
          last_main_radar_stamp_sec_ = pointcloud_data2->header.stamp.toSec();
          last_main_frame_id_ = static_cast<int>(pointcloud_data2->frameID);
        }
      }
      pointcloud_pub2_.publish(*pointcloud_data2);
    }
    else
    {
      ROS_INFO("pointcloud_data2 is null");
    }

    const rosbag::MessageInstance* pointcloud_slot3 = get_frame_msg_by_slot(3);
    boost::shared_ptr<arbe_msgs_rvizbag::wfAutosarData> pointcloud_data3 =
        pointcloud_slot3 ? pointcloud_slot3->instantiate<arbe_msgs_rvizbag::wfAutosarData>() : boost::shared_ptr<arbe_msgs_rvizbag::wfAutosarData>();
    if (pointcloud_data3)
    {
      if (pointcloud_data3->header.stamp.toSec() > 0.0)
      {
        std::lock_guard<std::mutex> lock(algo_warning_trace_mutex_);
        last_lgu_stamp_sec_[3] = pointcloud_data3->header.stamp.toSec();
        last_lgu_frame_id_[3] = static_cast<int>(pointcloud_data3->frameID);
        if (mainRadarIndex_ == 3)
        {
          last_main_radar_stamp_sec_ = pointcloud_data3->header.stamp.toSec();
          last_main_frame_id_ = static_cast<int>(pointcloud_data3->frameID);
        }
      }
      pointcloud_pub3_.publish(*pointcloud_data3);
    }
    else
    {
      ROS_INFO("pointcloud_data3 is null");
    }

    const rosbag::MessageInstance* pointcloud_slot4 = get_frame_msg_by_slot(4);
    boost::shared_ptr<arbe_msgs_rvizbag::wfAutosarData> pointcloud_data4 =
        pointcloud_slot4 ? pointcloud_slot4->instantiate<arbe_msgs_rvizbag::wfAutosarData>() : boost::shared_ptr<arbe_msgs_rvizbag::wfAutosarData>();
    if (pointcloud_data4)
    {
      if (pointcloud_data4->header.stamp.toSec() > 0.0)
      {
        std::lock_guard<std::mutex> lock(algo_warning_trace_mutex_);
        last_lgu_stamp_sec_[4] = pointcloud_data4->header.stamp.toSec();
        last_lgu_frame_id_[4] = static_cast<int>(pointcloud_data4->frameID);
        if (mainRadarIndex_ == 4)
        {
          last_main_radar_stamp_sec_ = pointcloud_data4->header.stamp.toSec();
          last_main_frame_id_ = static_cast<int>(pointcloud_data4->frameID);
        }
      }
      pointcloud_pub4_.publish(*pointcloud_data4);
    }
    else
    {
      ROS_INFO("pointcloud_data4 is null");
    }
  }

  {
    std::array<int, 5> lgu_frame_ids_snapshot;
    std::array<double, 5> lgu_stamp_secs_snapshot;
    double main_stamp_snapshot = 0.0;
    {
      std::lock_guard<std::mutex> lock(algo_warning_trace_mutex_);
      lgu_frame_ids_snapshot = last_lgu_frame_id_;
      lgu_stamp_secs_snapshot = last_lgu_stamp_sec_;
      main_stamp_snapshot = last_main_radar_stamp_sec_;
    }

    ros::Time display_time = main_time;
    if (display_time.toSec() <= 0.0 && main_stamp_snapshot > 0.0)
    {
      display_time.fromSec(main_stamp_snapshot);
    }

    QString main_bag_time_str = "N/A";
    QString main_bag_time_ros_sec_str = "N/A";
    if (display_time.toSec() > 0.0)
    {
      boost::posix_time::ptime boost_time = display_time.toBoost();
      boost_time += time_offset;
      main_bag_time_str = QString::fromStdString(boost::posix_time::to_simple_string(boost_time));
      main_bag_time_ros_sec_str = QString::number(display_time.toSec(), 'f', 6);
    }

    QString main_lgu_time_str = "N/A";
    QString main_lgu_time_ros_sec_str = "N/A";
    if (main_stamp_snapshot > 0.0)
    {
      ros::Time main_lgu_time;
      main_lgu_time.fromSec(main_stamp_snapshot);
      boost::posix_time::ptime boost_time = main_lgu_time.toBoost();
      boost_time += time_offset;
      main_lgu_time_str = QString::fromStdString(boost::posix_time::to_simple_string(boost_time));
      main_lgu_time_ros_sec_str = QString::number(main_stamp_snapshot, 'f', 6);
    }

    QString label_text = formatLguFrameIdLabel(frame_number,
                                               active_radar_id,
                                               lgu_frame_ids_snapshot,
                                               lgu_stamp_secs_snapshot,
                                               main_bag_time_str,
                                               main_bag_time_ros_sec_str,
                                               main_lgu_time_str,
                                               main_lgu_time_ros_sec_str);
    if (scene_mode)
    {
      label_text.replace("LGU Event Index", "Scene Frame Index");
      label_text.replace("Active Radar", "Anchor Radar");
      label_text.replace("EventBagTime", "SceneBagTime");
      label_text.replace("EventBagRosSec", "SceneBagRosSec");
    }
    QMetaObject::invokeMethod(this, [this, label_text]() {
      frame_id_label_->setText(label_text);
      frame_id_label_->repaint();
    }, Qt::QueuedConnection);
  }

  const rosbag::MessageInstance* camera_slot0 = get_frame_msg_by_slot(6);
  boost::shared_ptr<sensor_msgs::CompressedImage> camera_data0 =
      camera_slot0 ? camera_slot0->instantiate<sensor_msgs::CompressedImage>() : boost::shared_ptr<sensor_msgs::CompressedImage>();
  if (camera_data0)
  {
    camera_pub0_.publish(*camera_data0);
  }

  const rosbag::MessageInstance* camera_slot1 = get_frame_msg_by_slot(7);
  boost::shared_ptr<sensor_msgs::CompressedImage> camera_data1 =
      camera_slot1 ? camera_slot1->instantiate<sensor_msgs::CompressedImage>() : boost::shared_ptr<sensor_msgs::CompressedImage>();
  if (camera_data1)
  {
    camera_pub1_.publish(*camera_data1);
  }

  const rosbag::MessageInstance* camera_slot2 = get_frame_msg_by_slot(8);
  boost::shared_ptr<sensor_msgs::CompressedImage> camera_data2 =
      camera_slot2 ? camera_slot2->instantiate<sensor_msgs::CompressedImage>() : boost::shared_ptr<sensor_msgs::CompressedImage>();
  if (camera_data2)
  {
    camera_pub2_.publish(*camera_data2);
  }

  const rosbag::MessageInstance* camera_slot3 = get_frame_msg_by_slot(9);
  boost::shared_ptr<sensor_msgs::CompressedImage> camera_data3 =
      camera_slot3 ? camera_slot3->instantiate<sensor_msgs::CompressedImage>() : boost::shared_ptr<sensor_msgs::CompressedImage>();
  if (camera_data3)
  {
    camera_pub3_.publish(*camera_data3);
  }

  const rosbag::MessageInstance* camera_slot4 = get_frame_msg_by_slot(10);
  boost::shared_ptr<sensor_msgs::CompressedImage> camera_data4 =
      camera_slot4 ? camera_slot4->instantiate<sensor_msgs::CompressedImage>() : boost::shared_ptr<sensor_msgs::CompressedImage>();
  if (camera_data4)
  {
    camera_pub4_.publish(*camera_data4);
  }
  const rosbag::MessageInstance* camera_slot5 = get_frame_msg_by_slot(11);
  boost::shared_ptr<sensor_msgs::CompressedImage> camera_data5 =
      camera_slot5 ? camera_slot5->instantiate<sensor_msgs::CompressedImage>() : boost::shared_ptr<sensor_msgs::CompressedImage>();
  if (camera_data5)
  {
    camera_pub5_.publish(*camera_data5);
  }

  const rosbag::MessageInstance* camera_slot6 = get_frame_msg_by_slot(20);
  boost::shared_ptr<sensor_msgs::CompressedImage> camera_data6 =
      camera_slot6 ? camera_slot6->instantiate<sensor_msgs::CompressedImage>() : boost::shared_ptr<sensor_msgs::CompressedImage>();
  if (camera_data6)
  {
    camera_pub6_.publish(*camera_data6);
  }
}

void MyRvizPlugin::selectBagFile()
{
  QString file = QFileDialog::getOpenFileName(this, "Select Bag File", "", "Bag Files (*.bag)");
  if (!file.isEmpty())
  {
    bag_file_path_->setText(file);
    folder_mode_ = false;
    kpi_batch_running_ = false;
    bag_files_.clear();
    bag_csv_files_.clear();
    kpi_batch_rows_.clear();
    adas_batch_rows_.clear();
    kpi_output_dir_.clear();
    current_bag_index_ = -1;
    current_bag_label_->setText("Current Bag: N/A");
    current_csv_label_->setText("Matched CSV: N/A");
    current_loaded_bag_path_.clear();
    public_can_ch3_last_text_.clear();
    public_can_ch2_last_text_.clear();
    public_can_ch3_has_msg_ = false;
    public_can_ch2_has_msg_ = false;
    public_can_ch3_last_msg_index_ = -1;
    public_can_ch2_last_msg_index_ = -1;
    updatePublicCanTree(public_can_ch3_tree_, "No /rear/signals message loaded.");
    updatePublicCanTree(public_can_ch2_tree_, "No /front/signals message loaded.");
    warning_topic_label_->setText("Warning Topic: N/A");
    warning_summary_text_->clear();
    manual_tag_topic_label_->setText("Manual Tag Topic: N/A");
    manual_tag_summary_text_->clear();
    queuePanelControlRefresh(content_widget_);
  }
}

bool MyRvizPlugin::findMatchedLabelCsv(const std::string& bag_path, std::string& csv_path) const
{
  csv_path.clear();
  const QFileInfo bag_info(QString::fromStdString(bag_path));
  if (!bag_info.exists())
  {
    return false;
  }

  const QString dir = bag_info.absolutePath();
  const QString base = bag_info.completeBaseName();

  auto try_match_in_dir = [&](const QString& search_dir) -> bool {
    if (search_dir.isEmpty())
    {
      return false;
    }

    const QString prefer_gt = search_dir + "/" + base + "_corner_radar_gt.csv";
    if (QFileInfo::exists(prefer_gt))
    {
      csv_path = prefer_gt.toStdString();
      return true;
    }

    const QString fallback_same_base = search_dir + "/" + base + ".csv";
    if (QFileInfo::exists(fallback_same_base) &&
        !fallback_same_base.endsWith("_camera_mapping.csv"))
    {
      csv_path = fallback_same_base.toStdString();
      return true;
    }

    return false;
  };

  const QString gt_dir = gt_csv_folder_path_ ? gt_csv_folder_path_->text().trimmed() : QString();
  if (try_match_in_dir(gt_dir))
  {
    return true;
  }

  return try_match_in_dir(dir);
}

void MyRvizPlugin::rebuildFolderBagList()
{
  bag_files_.clear();
  bag_csv_files_.clear();
  current_bag_index_ = -1;
  current_loaded_bag_path_.clear();
  current_bag_label_->setText("Current Bag: N/A");
  current_csv_label_->setText("Matched CSV: N/A");
  warning_topic_label_->setText("Warning Topic: N/A");
  warning_summary_text_->clear();
  manual_tag_topic_label_->setText("Manual Tag Topic: N/A");
  manual_tag_summary_text_->clear();

  const QString folder = folder_path_->text().trimmed();
  if (folder.isEmpty())
  {
    folder_mode_ = false;
    bag_file_path_->clear();
    return;
  }

  QDir dir(folder);
  if (!dir.exists())
  {
    folder_mode_ = false;
    bag_file_path_->clear();
    return;
  }

  folder_mode_ = true;
  QStringList filters;
  filters << "*.bag";
  dir.setNameFilters(filters);
  QStringList bag_list = dir.entryList(QDir::Files | QDir::NoDotAndDotDot, QDir::Name);
  QStringList missing_csv_bags;
  const bool require_pair = kpi_pair_mode_checkbox_->isChecked();

  for (const QString& bag_file : bag_list)
  {
    const std::string bag_path = dir.filePath(bag_file).toStdString();
    std::string csv_path;
    if (require_pair)
    {
      if (!findMatchedLabelCsv(bag_path, csv_path))
      {
        missing_csv_bags.push_back(bag_file);
        continue;
      }
    }
    bag_files_.push_back(bag_path);
    bag_csv_files_.push_back(csv_path);
  }

  if (!bag_files_.empty())
  {
    bag_file_path_->setText(QString::fromStdString(bag_files_[0]));
    ROS_INFO("Found %lu bag files in folder: %s", bag_files_.size(), folder.toStdString().c_str());
    if (require_pair && !missing_csv_bags.isEmpty())
    {
      const int limit = std::min(10, missing_csv_bags.size());
      QStringList preview = missing_csv_bags.mid(0, limit);
      QString msg = "Skipped bags without matched CSV:\n" + preview.join("\n");
      if (missing_csv_bags.size() > limit)
      {
        msg += QString("\n... and %1 more").arg(missing_csv_bags.size() - limit);
      }
      QMessageBox::information(this, "KPI Batch Pairing", msg);
    }
  }
  else
  {
    ROS_WARN("No bag files found in folder: %s", folder.toStdString().c_str());
    folder_mode_ = false;
    bag_file_path_->clear();
  }
}

void MyRvizPlugin::updateCurrentCsvLabel()
{
  if (!folder_mode_ || current_bag_index_ < 0 ||
      current_bag_index_ >= static_cast<int>(bag_csv_files_.size()))
  {
    current_csv_label_->setText("Matched CSV: N/A");
    return;
  }

  const std::string& csv = bag_csv_files_[current_bag_index_];
  if (csv.empty())
  {
    current_csv_label_->setText("Matched CSV: N/A");
    return;
  }

  current_csv_label_->setText("Matched CSV: " + QString::fromStdString(csv));
}

QString MyRvizPlugin::resolveKpiBatchScriptPath() const
{
  std::string ros_param_path;
  if (ros::param::get("/kpi/frame_sync_kpi_script_path", ros_param_path))
  {
    const QString cfg = QFileInfo(QString::fromStdString(ros_param_path)).absoluteFilePath();
    if (QFileInfo::exists(cfg))
    {
      return cfg;
    }
  }
  if (ros::param::get("/kpi/batch_script_path", ros_param_path))
  {
    const QString cfg = QFileInfo(QString::fromStdString(ros_param_path)).absoluteFilePath();
    if (QFileInfo::exists(cfg))
    {
      return cfg;
    }
  }

  QStringList candidates;
  candidates << QDir(QDir::currentPath()).absoluteFilePath("bag_csv_kpi_framesync.py");

  const std::string pkg_path = ros::package::getPath("my_rviz_plugin");
  if (!pkg_path.empty())
  {
    QDir dir(QString::fromStdString(pkg_path));
    for (int i = 0; i < 14; ++i)
    {
      candidates << dir.absoluteFilePath("bag_csv_kpi_framesync.py");
      if (!dir.cdUp())
      {
        break;
      }
    }
  }

  for (const QString& c : candidates)
  {
    if (QFileInfo::exists(c))
    {
      return QFileInfo(c).absoluteFilePath();
    }
  }
  return QString();
}

void MyRvizPlugin::runKpiExportForCurrentBag()
{
  if (!kpi_batch_running_)
  {
    return;
  }
  if (current_bag_index_ < 0 || current_bag_index_ >= static_cast<int>(bag_files_.size()))
  {
    return;
  }

  KpiBatchResultRow row;
  row.bag_path = QString::fromStdString(bag_files_[current_bag_index_]);
  row.csv_path = (current_bag_index_ < static_cast<int>(bag_csv_files_.size()))
                   ? QString::fromStdString(bag_csv_files_[current_bag_index_])
                   : QString();
  row.status = "FAILED";

  const QString base = QFileInfo(row.bag_path).completeBaseName();
  const QString algo_warning_trace_csv = writeAlgoWarningTraceCsv(base);

  if (!kpi_pair_mode_active_)
  {
    row.summary_path.clear();
    row.events_path.clear();

    if (kpi_output_dir_.isEmpty())
    {
      row.detail = "adas output dir is empty";
      kpi_batch_rows_.push_back(row);
      return;
    }
    if (algo_warning_trace_csv.isEmpty())
    {
      row.detail = "failed to write algo warning trace csv";
      kpi_batch_rows_.push_back(row);
      return;
    }

    const int trigger_count = collectAdasTriggersForCurrentBag(base, row.bag_path);
    row.status = "OK";
    row.detail = QString("adas_trigger_count=%1; trace_csv=%2")
                   .arg(trigger_count)
                   .arg(QFileInfo(algo_warning_trace_csv).fileName());
    kpi_batch_rows_.push_back(row);
    return;
  }

  row.summary_path = QDir(kpi_output_dir_).absoluteFilePath(base + "_adas_kpi_summary.csv");
  row.events_path = QDir(kpi_output_dir_).absoluteFilePath(base + "_adas_kpi_summary_events.csv");

  if (row.csv_path.isEmpty())
  {
    row.detail = "missing matched csv";
    kpi_batch_rows_.push_back(row);
    return;
  }
  if (kpi_batch_script_path_.isEmpty() || !QFileInfo::exists(kpi_batch_script_path_))
  {
    row.detail = "bag_csv_kpi_framesync.py not found";
    kpi_batch_rows_.push_back(row);
    return;
  }
  if (kpi_output_dir_.isEmpty())
  {
    row.detail = "kpi output dir is empty";
    kpi_batch_rows_.push_back(row);
    return;
  }
  if (algo_warning_trace_csv.isEmpty())
  {
    row.detail = "failed to write algo warning trace csv";
    kpi_batch_rows_.push_back(row);
    return;
  }

  QProcess proc;
  QStringList args;
  args << kpi_batch_script_path_
       << "--bag" << row.bag_path
       << "--csv" << row.csv_path
       << "--output-dir" << kpi_output_dir_
       << "--warning-csv" << algo_warning_trace_csv
       << "--warning-topic" << "/corner_radar/warning_status_with_frame"
       << "--lgu-prefix" << "/wf/corner_radar/lgu_data_";

  proc.start("python3", args);
  if (!proc.waitForStarted(5000))
  {
    row.detail = "failed to start python3";
    kpi_batch_rows_.push_back(row);
    return;
  }

  proc.waitForFinished(-1);
  const QString out = QString::fromUtf8(proc.readAllStandardOutput()).trimmed();
  const QString err = QString::fromUtf8(proc.readAllStandardError()).trimmed();
  const bool ok =
      (proc.exitStatus() == QProcess::NormalExit) &&
      (proc.exitCode() == 0) &&
      QFileInfo::exists(row.summary_path) &&
      QFileInfo::exists(row.events_path);
  if (ok)
  {
    row.status = "OK";
    row.detail = "done; warning_source=/corner_radar/warning_status_with_frame (trace csv)";
  }
  else
  {
    QString detail = QString("python3 exit=%1").arg(proc.exitCode());
    if (!err.isEmpty())
    {
      detail += "; " + err;
    }
    else if (!out.isEmpty())
    {
      detail += "; " + out;
    }
    row.detail = detail;
  }

  kpi_batch_rows_.push_back(row);
}

void MyRvizPlugin::writeKpiBatchIndex()
{
  if (kpi_output_dir_.isEmpty())
  {
    return;
  }

  const QString index_path = QDir(kpi_output_dir_).absoluteFilePath("batch_kpi_index.csv");
  QFile file(index_path);
  if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate | QIODevice::Text))
  {
    return;
  }

  QTextStream ts(&file);
  auto csv_escape = [](const QString& value) {
    QString out = value;
    out.replace("\"", "\"\"");
    return QString("\"%1\"").arg(out);
  };

  ts << "bag_path,csv_path,status,summary_path,events_path,detail\n";
  for (const auto& row : kpi_batch_rows_)
  {
    ts << csv_escape(row.bag_path) << ","
       << csv_escape(row.csv_path) << ","
       << csv_escape(row.status) << ","
       << csv_escape(row.summary_path) << ","
       << csv_escape(row.events_path) << ","
       << csv_escape(row.detail) << "\n";
  }
  file.close();
}

void MyRvizPlugin::selectFolder()
{
  QString folder = QFileDialog::getExistingDirectory(this, "Select Bag Folder", "");
  if (!folder.isEmpty())
  {
    folder_path_->setText(folder);
    folder_mode_ = true;
    kpi_batch_running_ = false;
    bag_files_.clear();
    bag_csv_files_.clear();
    kpi_batch_rows_.clear();
    adas_batch_rows_.clear();
    kpi_output_dir_.clear();
    current_bag_index_ = -1;
    current_loaded_bag_path_.clear();
    current_csv_label_->setText("Matched CSV: N/A");
    warning_topic_label_->setText("Warning Topic: N/A");
    warning_summary_text_->clear();
    manual_tag_topic_label_->setText("Manual Tag Topic: N/A");
    manual_tag_summary_text_->clear();

    rebuildFolderBagList();
    queuePanelControlRefresh(content_widget_);
  }
}

void MyRvizPlugin::selectGtCsvFolder()
{
  QString folder = QFileDialog::getExistingDirectory(this, "Select GT CSV Folder", gt_csv_folder_path_->text().trimmed());
  if (folder.isEmpty())
  {
    return;
  }

  gt_csv_folder_path_->setText(folder);
  if (!folder_path_->text().trimmed().isEmpty())
  {
    rebuildFolderBagList();
  }
  queuePanelControlRefresh(content_widget_);
}

void MyRvizPlugin::startKpiBatch()
{
  if (kpi_batch_running_)
  {
    QMessageBox::information(this, "KPI Batch", "KPI batch is already running.");
    return;
  }

  if (folder_path_->text().isEmpty() || bag_files_.empty())
  {
    selectFolder();
    if (bag_files_.empty())
    {
      return;
    }
  }

  if (!folder_mode_ || bag_files_.empty())
  {
    QMessageBox::warning(this, "KPI Batch", "Please select a folder first.");
    return;
  }

  const bool require_pair = kpi_pair_mode_checkbox_->isChecked();

  if (!folder_path_->text().trimmed().isEmpty())
  {
    rebuildFolderBagList();
  }

  if (require_pair)
  {
    if (bag_csv_files_.size() != bag_files_.size())
    {
      QMessageBox::warning(this, "KPI Batch", "bag/csv pair list is invalid. Re-select folder.");
      return;
    }
    for (size_t i = 0; i < bag_csv_files_.size(); ++i)
    {
      if (bag_csv_files_[i].empty())
      {
        QMessageBox::warning(this, "KPI Batch", "Found bag without CSV pair. Re-select folder.");
        return;
      }
    }
  }

  const QString confirm = require_pair
                            ? QString("Start FrameSync KPI batch playback?\nBags: %1")
                            : QString("Start bag-only batch playback and export ADAS trigger report?\nBags: %1")
                            .arg(static_cast<int>(bag_files_.size()));
  if (QMessageBox::question(this, "KPI Batch", confirm, QMessageBox::Yes | QMessageBox::No) != QMessageBox::Yes)
  {
    return;
  }

  if (require_pair)
  {
    kpi_batch_script_path_ = resolveKpiBatchScriptPath();
    if (kpi_batch_script_path_.isEmpty())
    {
      QMessageBox::critical(this, "KPI Batch", "Cannot find bag_csv_kpi_framesync.py.\n"
                                               "Set /kpi/frame_sync_kpi_script_path or place script in workspace.");
      return;
    }
  }
  else
  {
    kpi_batch_script_path_.clear();
  }

  kpi_pair_mode_active_ = require_pair;
  const QString output_root = QDir::currentPath();
  kpi_output_dir_ = QDir(output_root).absoluteFilePath(
      (require_pair ? "kpi_reports_" : "adas_reports_") + QDateTime::currentDateTime().toString("yyyyMMdd_HHmmss"));
  QDir().mkpath(kpi_output_dir_);
  kpi_batch_rows_.clear();
  adas_batch_rows_.clear();

  publish_warning_raw_checkbox_->setChecked(false);
  {
    const QSignalBlocker blocker(scene_mode_checkbox_);
    scene_mode_checkbox_->setChecked(false);
  }
  scene_mode_checkbox_->setEnabled(false);
  kpi_batch_running_ = true;
  current_bag_index_ = -1;
  resetAlgoWarningTrace();
  readBagFile();
  if (current_loaded_bag_path_.empty())
  {
    return;
  }

  QTimer::singleShot(150, this, [this]() {
    bContinuePlayFlag = true;
    playBag();
  });
}

void MyRvizPlugin::finishKpiBatchWithMessage(const QString& message)
{
  stopKpiBatchPlaybackWatchdog();
  writeKpiBatchIndex();

  QString final_message = message;
  if (!kpi_pair_mode_active_)
  {
    const QString adas_csv = writeAdasBatchReportCsv();
    if (!adas_csv.isEmpty())
    {
      final_message += QString("\nADAS trigger report:\n%1").arg(adas_csv);
    }
    const QString fctb_csv = writeFctbBatchReportCsv();
    if (!fctb_csv.isEmpty())
    {
      final_message += QString("\nFCTB trigger report:\n%1").arg(fctb_csv);
    }
  }

  QMessageBox::information(this, "KPI Batch", final_message);
  kpi_batch_running_ = false;
  folder_mode_ = false;
  scene_mode_checkbox_->setEnabled(!current_loaded_bag_path_.empty());
  bag_files_.clear();
  bag_csv_files_.clear();
  adas_batch_rows_.clear();
  current_bag_index_ = -1;
  current_csv_label_->setText("Matched CSV: N/A");
  current_bag_label_->setText("Current Bag: N/A");
  current_loaded_bag_path_.clear();
}

void MyRvizPlugin::skipCurrentBatchBag(const QString& status, const QString& detail)
{
  stopKpiBatchPlaybackWatchdog();

  const std::string bag_path_std =
      (current_bag_index_ >= 0 && current_bag_index_ < static_cast<int>(bag_files_.size()))
          ? bag_files_[current_bag_index_]
          : std::string();
  const std::string csv_path_std =
      (current_bag_index_ >= 0 && current_bag_index_ < static_cast<int>(bag_csv_files_.size()))
          ? bag_csv_files_[current_bag_index_]
          : std::string();

  KpiBatchResultRow row;
  row.bag_path = QString::fromStdString(bag_path_std);
  row.csv_path = QString::fromStdString(csv_path_std);
  row.status = status;
  row.summary_path.clear();
  row.events_path.clear();
  row.detail = detail;
  kpi_batch_rows_.push_back(row);

  ROS_ERROR("Skip bag during KPI batch: status=%s bag=%s ; detail=%s",
            status.toStdString().c_str(), bag_path_std.c_str(), detail.toStdString().c_str());

  current_loaded_bag_path_.clear();
  warning_topic_label_->setText("Warning Topic: N/A");
  warning_summary_text_->clear();
  manual_tag_topic_label_->setText("Manual Tag Topic: N/A");
  manual_tag_summary_text_->clear();
  resetAlgoWarningTrace();

  if (current_bag_index_ >= static_cast<int>(bag_files_.size()) - 1)
  {
    const QString done_msg = kpi_pair_mode_active_
                                 ? QString("KPI batch finished.\nOutput dir:\n%1")
                                       .arg(kpi_output_dir_.isEmpty() ? "N/A" : kpi_output_dir_)
                                 : QString("Bag-only ADAS trigger batch finished.\nIntermediate output dir:\n%1")
                                       .arg(kpi_output_dir_.isEmpty() ? "N/A" : kpi_output_dir_);
    finishKpiBatchWithMessage(done_msg);
    return;
  }

  QTimer::singleShot(0, this, [this]() {
    readBagFile();
    if (!current_loaded_bag_path_.empty())
    {
      QTimer::singleShot(150, this, [this]() {
        bContinuePlayFlag = true;
        playBag();
      });
    }
  });
}

void MyRvizPlugin::skipCurrentBatchBagOnLoadFailure(const QString& detail)
{
  skipCurrentBatchBag("SKIPPED", detail);
}

void MyRvizPlugin::resetKpiBatchPlaybackWatchdog()
{
  if (!kpi_batch_watchdog_timer_ || !kpi_batch_running_ || internal_stop_request_ || kpi_batch_timeout_handling_)
  {
    return;
  }
  kpi_batch_watchdog_timer_->start(kpi_batch_playback_timeout_ms_);
}

void MyRvizPlugin::stopKpiBatchPlaybackWatchdog()
{
  if (kpi_batch_watchdog_timer_)
  {
    kpi_batch_watchdog_timer_->stop();
  }
}

void MyRvizPlugin::handleKpiBatchPlaybackTimeout()
{
  if (!kpi_batch_running_ || !folder_mode_ || kpi_batch_timeout_handling_)
  {
    return;
  }

  kpi_batch_timeout_handling_ = true;
  const QString bag_path =
      (current_bag_index_ >= 0 && current_bag_index_ < static_cast<int>(bag_files_.size()))
          ? QString::fromStdString(bag_files_[current_bag_index_])
          : QString("N/A");
  const QString detail = QString("playback timeout: no LGU publish or matching completion callback progress for %1 ms; active_radar=%2; frame_id=%3; lgu_event=%4; bag=%5")
                             .arg(kpi_batch_playback_timeout_ms_)
                             .arg(pending_service_radar_id_.load())
                             .arg(pending_service_frame_id_.load())
                             .arg(bag_reader_->getCurrentFrame())
                             .arg(bag_path);

  ROS_ERROR("%s", detail.toStdString().c_str());
  internal_stop_request_ = true;
  stopBag();
  internal_stop_request_ = false;
  skipCurrentBatchBag("TIMEOUT_SKIPPED", detail);
  kpi_batch_timeout_handling_ = false;
}



void MyRvizPlugin::readBagFile()
{
  std::string path;
  if (folder_mode_)// 判断是否处于文件夹模式（批量播放模式）
  {
    if (current_bag_index_ >= static_cast<int>(bag_files_.size()) - 1)// 是否已经处理完所有bag文件
    {
      current_bag_label_->setText("Current Bag: No more files");
      folder_mode_ = false;
      kpi_batch_running_ = false;
      current_bag_index_ = -1;
      bag_files_.clear();
      bag_csv_files_.clear();
      bag_file_path_->clear();
      current_loaded_bag_path_.clear();
      current_csv_label_->setText("Matched CSV: N/A");
      warning_topic_label_->setText("Warning Topic: N/A");
      warning_summary_text_->clear();
      manual_tag_topic_label_->setText("Manual Tag Topic: N/A");
      manual_tag_summary_text_->clear();
      return;
    }
    current_bag_index_++;
    path = bag_files_[current_bag_index_];
    bag_file_path_->setText(QString::fromStdString(path));
    updateCurrentCsvLabel();
    ros::param::set("/kpi/current_bag_path", path);
    if (current_bag_index_ < static_cast<int>(bag_csv_files_.size()))
    {
      ros::param::set("/kpi/current_label_csv", bag_csv_files_[current_bag_index_]);
    }
    else
    {
      ros::param::set("/kpi/current_label_csv", std::string(""));
    }
  }
  else// 单文件模式：直接获取界面上输入的文件路径
  {
    path = bag_file_path_->text().toStdString();
    current_csv_label_->setText("Matched CSV: N/A");
  }

  if (!path.empty())
  {
    if (kpi_batch_running_)
    {
      resetAlgoWarningTrace();
    }
    ros::param::set("/kpi/current_bag_path", path);
    int bag_switch_epoch = 0;
    ros::param::param<int>("/kpi/bag_switch_epoch", bag_switch_epoch, 0);
    ros::param::set("/kpi/bag_switch_epoch", bag_switch_epoch + 1);

    //recreateBagReader();
    play_button_->setEnabled(false);
    stop_button_->setEnabled(false);
    frame_spinner_->setEnabled(false);
    step_spinner_->setEnabled(false);
    step_forward_button_->setEnabled(false);
    step_backward_button_->setEnabled(false);
    play_rate_combo_->setEnabled(false);
    frame_slider_->setEnabled(false);
    select_main_radar_->setEnabled(false);
    current_bag_label_->setText("Current Bag: " + QString::fromStdString(path));
    // 调用BagReader读取bag文件，同时统计各雷达的帧数
    try
    {
      bag_reader_->readBagFile(path, frame_count0,frame_count1,frame_count2,frame_count3, frame_count4);
    }
    catch (const std::exception& ex)
    {
      const QString detail = QString("bag open/read failed: %1").arg(ex.what());
      ROS_ERROR("Failed to read bag %s: %s", path.c_str(), ex.what());
      if (kpi_batch_running_ && folder_mode_)
      {
        skipCurrentBatchBagOnLoadFailure(detail);
      }
      else
      {
        current_loaded_bag_path_.clear();
        QMessageBox::critical(this, "Read Bag", QString("Failed to read bag:\n%1\n\n%2")
                                                   .arg(QString::fromStdString(path))
                                                   .arg(detail));
      }
      return;
    }
    catch (...)
    {
      const QString detail = "bag open/read failed: unknown exception";
      ROS_ERROR("Failed to read bag %s: unknown exception", path.c_str());
      if (kpi_batch_running_ && folder_mode_)
      {
        skipCurrentBatchBagOnLoadFailure(detail);
      }
      else
      {
        current_loaded_bag_path_.clear();
        QMessageBox::critical(this, "Read Bag", QString("Failed to read bag:\n%1\n\n%2")
                                                   .arg(QString::fromStdString(path))
                                                   .arg(detail));
      }
      return;
    }
    current_loaded_bag_path_ = path;

    const int total_lgu_frames = frame_count0 + frame_count1 + frame_count2 + frame_count3 + frame_count4;
    if (total_lgu_frames <= 0)
    {
      const QString detail = "bag contains no LGU messages on /wf/corner_radar/lgu_data_0..4";
      ROS_ERROR("No LGU frames found in bag %s", path.c_str());
      current_loaded_bag_path_.clear();
      if (kpi_batch_running_ && folder_mode_)
      {
        skipCurrentBatchBag("NO_LGU_SKIPPED", detail);
      }
      else
      {
        QMessageBox::warning(this, "Read Bag", detail);
      }
      return;
    }

    // 更新界面显示各雷达的帧数统计信息
    frame_count_label_->setText("Frame Count: Radar(0) " + QString::number(frame_count0) + 
                               ";Radar(1-LT) " + QString::number(frame_count1) +
                               ";Radar(2-RT) " + QString::number(frame_count2) +
                               ";Radar(3-LB) " + QString::number(frame_count3) + 
                               ";Radar(4-RB) " + QString::number(frame_count4));

    const int resolved_main_radar = resolvePlayableMainRadarIndex();
    if (resolved_main_radar >= 0)
    {
      if (resolved_main_radar != mainRadarIndex_)
      {
        ROS_WARN("Selected main radar %d has no frames in bag %s. Fallback to radar %d.",
                 mainRadarIndex_, path.c_str(), resolved_main_radar);
        mainRadarIndex_ = resolved_main_radar;
        bag_reader_->selectMainRadar(mainRadarIndex_);
        const QSignalBlocker blocker(select_main_radar_);
        select_main_radar_->setCurrentIndex(mainRadarIndex_);
      }
      else
      {
        bag_reader_->selectMainRadar(mainRadarIndex_);
      }
    }
    else
    {
      ROS_WARN("No playable radar frames found in bag %s for playback anchors 0~4.", path.c_str());
    }

    if (!kpi_batch_running_ && !folder_mode_)
    {
      const QSignalBlocker blocker(scene_mode_checkbox_);
      scene_mode_checkbox_->setChecked(true);
    }
    updateFrameControlsForSelectedRadar();
    refreshWarningSummary(path);
    refreshManualTagSummary(path);

    if (kpi_batch_running_)
    {
      play_button_->setEnabled(false);
      stop_button_->setEnabled(true);
      frame_spinner_->setEnabled(false);
      step_spinner_->setEnabled(false);
      step_forward_button_->setEnabled(false);
      step_backward_button_->setEnabled(false);
      play_rate_combo_->setEnabled(false);
      frame_slider_->setEnabled(false);
      select_main_radar_->setEnabled(false);
      start_kpi_batch_button_->setEnabled(false);
    }
    else
    {
      play_button_->setEnabled(true);
      stop_button_->setEnabled(false);
      frame_spinner_->setEnabled(true);
      step_spinner_->setEnabled(true);
      step_forward_button_->setEnabled(true);
      step_backward_button_->setEnabled(true);
      play_rate_combo_->setEnabled(true);
      frame_slider_->setEnabled(true);
      select_main_radar_->setEnabled(true);
      scene_mode_checkbox_->setEnabled(true);
      start_kpi_batch_button_->setEnabled(true);
    }

    ROS_INFO("———Bag file read and cached success———: %s", path.c_str());
    queuePanelControlRefresh(content_widget_);
  }
}

void MyRvizPlugin::jumpToFrame()
{
  if(!bContinuePlayFlag)
  {
    const bool scene_mode = scene_mode_checkbox_->isChecked()
                            && !kpi_batch_running_ && !folder_mode_;
    if (scene_mode)
    {
      std::lock_guard<std::mutex> lock(pending_scene_service_mutex_);
      if (scene_dispatch_active_)
      {
        ROS_WARN("[FRAME_PLAYER] current debug scene is still waiting for algorithm callbacks");
        const QSignalBlocker blocker(frame_spinner_);
        frame_spinner_->setValue(bag_reader_->getCurrentFrame());
        return;
      }
    }

    int frame_number = frame_spinner_->value();
    ROS_INFO("[FRAME_PLAYER] jumpToFrame frame=%d", frame_number);
    if (frame_number >= -1 )
    {
      if (scene_mode)
      {
        const bool moving_forward = frame_number > bag_reader_->getCurrentFrame();
        bag_reader_->jumpToSceneFrame(frame_number, moving_forward);
      }
      else
      {
        {
          std::lock_guard<std::mutex> lock(pending_scene_service_mutex_);
          const bool has_pending_event = std::any_of(
              pending_event_frame_ids_.begin(), pending_event_frame_ids_.end(),
              [](const std::deque<int>& frames) { return !frames.empty(); });
          if (has_pending_event)
          {
            ROS_WARN("[FRAME_PLAYER] current LGU event is still waiting for algorithm callback");
            const QSignalBlocker blocker(frame_spinner_);
            frame_spinner_->setValue(bag_reader_->getCurrentFrame());
            return;
          }
        }
        bag_reader_->jumpToFrame(frame_number);
      }
    }
  }
}

void MyRvizPlugin::stepForward()
{
  int step = step_spinner_->value();
  int new_frame = std::min(frame_spinner_->value() + step, frame_spinner_->maximum() - 1);
  frame_spinner_->setValue(new_frame);
}

void MyRvizPlugin::stepBackward()
{
  int step = step_spinner_->value();
  int new_frame = std::max(frame_spinner_->value() - step, frame_spinner_->minimum());
  frame_spinner_->setValue(new_frame);
}
void MyRvizPlugin::playBag()
{
  ROS_INFO("[FRAME_PLAYER] playBag clicked current_frame=%d mainRadar=%d current_bag=%s", bag_reader_->getCurrentFrame(), mainRadarIndex_, current_loaded_bag_path_.c_str());
  bContinuePlayFlag = true;
  const bool scene_mode = scene_mode_checkbox_->isChecked()
                          && !kpi_batch_running_ && !folder_mode_;
  const bool is_batch = kpi_batch_running_ || folder_mode_;
  if (is_batch)
  {
    ros::param::param<bool>("/kpi/respect_bag_timing", kpi_respect_bag_timing_, true);
  }
  const bool respect_bag_timing = !is_batch || kpi_respect_bag_timing_;
  ROS_INFO("[FRAME_PLAYER] timing mode=%s",
           respect_bag_timing ? "recorded-time" : "accelerated");
  bag_reader_->playBag(scene_mode, respect_bag_timing);
  if (kpi_batch_running_)
  {
    resetKpiBatchPlaybackWatchdog();
  }

  play_button_->setEnabled(false);
  stop_button_->setEnabled(true);
  frame_spinner_->setEnabled(false);
  step_spinner_->setEnabled(false);
  step_forward_button_->setEnabled(false);
  step_backward_button_->setEnabled(false);
  play_rate_combo_->setEnabled(false);
  frame_slider_->setEnabled(false);
  select_main_radar_->setEnabled(false);
  scene_mode_checkbox_->setEnabled(false);
  queuePanelControlRefresh(content_widget_);
}



void MyRvizPlugin::stopBag()
{
  bContinuePlayFlag = false;
  stopKpiBatchPlaybackWatchdog();
  pending_service_radar_id_ = -1;
  pending_service_frame_id_ = -1;
  {
    std::lock_guard<std::mutex> lock(pending_scene_service_mutex_);
    for (auto& pending_frames : pending_event_frame_ids_)
    {
      pending_frames.clear();
    }
    scene_dispatch_active_ = false;
    pending_scene_frame_ids_.fill(-1);
    pending_scene_completed_.fill(false);
  }

  bag_reader_->stopBag();

  if (kpi_batch_running_ && !internal_stop_request_)
  {
    // User actively stops current batch.
    const QString stop_msg = kpi_pair_mode_active_
                               ? QString("KPI batch stopped by user.\nPartial outputs in:\n%1")
                                   .arg(kpi_output_dir_.isEmpty() ? "N/A" : kpi_output_dir_)
                               : QString("Bag-only ADAS trigger batch stopped by user.\nADAS trigger report:\n%1\nIntermediate output dir:\n%2")
                                   .arg("N/A")
                                   .arg(kpi_output_dir_.isEmpty() ? "N/A" : kpi_output_dir_);
    finishKpiBatchWithMessage(stop_msg);
  }

  play_button_->setEnabled(true);
  stop_button_->setEnabled(false);
  
  step_spinner_->setEnabled(true);
  frame_spinner_->setEnabled(true);
  step_forward_button_->setEnabled(true);
  step_backward_button_->setEnabled(true);
  play_rate_combo_->setEnabled(true);
  frame_slider_->setEnabled(true);
  select_main_radar_->setEnabled(true);
  scene_mode_checkbox_->setEnabled(!kpi_batch_running_ && !folder_mode_ && !current_loaded_bag_path_.empty());
  start_kpi_batch_button_->setEnabled(true);
  queuePanelControlRefresh(content_widget_);
}


void MyRvizPlugin::updatePlayRate()
{
  double rate = play_rate_combo_->currentText().toDouble();
  bag_reader_->setPlayRate(rate);
}

void MyRvizPlugin::sliderValueChanged(int value)
{
  if(frame_spinner_->value() >= frame_spinner_->maximum() || value >= frame_spinner_->maximum())
  {
    frame_spinner_->setValue(0);
    frame_slider_->setValue(0);
  }
  else
  {
    frame_spinner_->setValue(value);
  }
}


void MyRvizPlugin::selectMainRadar()
{
  mainRadarIndex_ = select_main_radar_->currentIndex();

  if (!current_loaded_bag_path_.empty() && frameCountForRadar(mainRadarIndex_) <= 0)
  {
    const int fallback_radar = resolvePlayableMainRadarIndex();
    if (fallback_radar >= 0 && fallback_radar != mainRadarIndex_)
    {
      ROS_WARN("Selected Scene anchor radar %d has no data; fallback to radar %d",
               mainRadarIndex_, fallback_radar);
      mainRadarIndex_ = fallback_radar;
      const QSignalBlocker blocker(select_main_radar_);
      select_main_radar_->setCurrentIndex(mainRadarIndex_);
    }
  }

  bag_reader_->selectMainRadar(mainRadarIndex_);
  updateFrameControlsForSelectedRadar();
  {
    const QSignalBlocker spinner_blocker(frame_spinner_);
    const QSignalBlocker slider_blocker(frame_slider_);
    frame_spinner_->setValue(0);
    frame_slider_->setValue(0);
  }

  if (!current_loaded_bag_path_.empty())
  {
    refreshWarningSummary(current_loaded_bag_path_);
    refreshManualTagSummary(current_loaded_bag_path_);
  }

  if(frame_spinner_->value() >= frame_spinner_->maximum())
  {
    frame_spinner_->setValue(0);
    frame_slider_->setValue(0);
  }
}

void MyRvizPlugin::refreshWarningSummary(const std::string& bag_path)
{
  if (bag_path.empty())
  {
    warning_topic_label_->setText("Warning Topic: N/A");
    warning_summary_text_->clear();
    return;
  }

  const bool has_warning_topic = bag_reader_->hasWarningTopic();
  const size_t warning_count = bag_reader_->getWarningCount();
  const size_t triggered_warning_count = bag_reader_->getTriggeredWarningCount();

  QString topic_label = QString("Warning Topic: %1 (raw=%2, triggered=%3)")
                          .arg(has_warning_topic ? "FOUND" : "NOT FOUND")
                          .arg(static_cast<qulonglong>(warning_count))
                          .arg(static_cast<qulonglong>(triggered_warning_count));
  warning_topic_label_->setText(topic_label);

  const std::string summary = bag_reader_->buildWarningSummary(mainRadarIndex_, 0);
  warning_summary_text_->setPlainText(QString::fromStdString(summary));
}

void MyRvizPlugin::refreshManualTagSummary(const std::string& bag_path)
{
  if (bag_path.empty())
  {
    manual_tag_topic_label_->setText("Manual Tag Topic: N/A");
    manual_tag_summary_text_->clear();
    return;
  }

  const bool has_manual_tag_topic = bag_reader_->hasManualTagTopic();
  const size_t manual_tag_count = bag_reader_->getManualTagCount();
  const QString topic_label = QString("Manual Tag Topic: %1 (count=%2)  topic=%3")
                                  .arg(has_manual_tag_topic ? "FOUND" : "NOT FOUND")
                                  .arg(static_cast<qulonglong>(manual_tag_count))
                                  .arg(kManualTestTagTopicDisplay);
  manual_tag_topic_label_->setText(topic_label);
  manual_tag_summary_text_->setPlainText(
      QString::fromStdString(bag_reader_->buildManualTagSummary(mainRadarIndex_, 0)));
}

void MyRvizPlugin::updateSliderAndSpinner()
{
  frame_slider_->setValue(bag_reader_->getCurrentFrame());
  frame_slider_->repaint();
  frame_spinner_->repaint();
}

} // namespace my_rviz_plugin

PLUGINLIB_EXPORT_CLASS(my_rviz_plugin::MyRvizPlugin, rviz::Panel)
