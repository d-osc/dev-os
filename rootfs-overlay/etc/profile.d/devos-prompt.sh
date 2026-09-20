# BusyBox ash and Bash expand these escapes each time the prompt is displayed.
# Keep non-interactive shells quiet and show # automatically for root.
case $- in
    *i*) export PS1='\u@\h:\w\$ ' ;;
esac
